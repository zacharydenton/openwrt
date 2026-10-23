#!/usr/bin/env python3
"""Exercise the allocation-free removal command and rejecting-serializer drain."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def extract(source, name):
    m = re.search(r'^(?:static\s+)?(?:void|int)\s+(?:__MTLK_IFUNC\s+)?' +
                  name + r'\s*\([^;]*?\)\s*\{', source, re.M)
    assert m, name
    end, depth = m.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[m.start():end]


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tree', type=Path)
p.add_argument('--cc', default='cc')
p.add_argument('--qemu', type=Path)
a = p.parse_args()
core = (a.tree / 'wireless/driver/linux/core.c').read_text()
serializer = (a.tree / 'wireless/driver/shared/mtlk_serializer.c').read_text()
radio = (a.tree / 'wireless/driver/linux/wave_radio.c').read_text()
quiesce = extract(radio, 'wave_radio_scan_quiesce')
assert quiesce.index('scan_support_prepare_remove') < quiesce.index('mtlk_core_scan_quiesce')
assert quiesce.index('mtlk_core_scan_quiesce') < quiesce.index('mtlk_df_user_quiesce_prop_dfs_wq')
assert '_wave_radio_abort_and_prevent_scan' not in quiesce
assert 'szr->stop_done = FALSE;' in extract(serializer, 'mtlk_serializer_start')
assert 'szr->stop_done = TRUE;' in extract(serializer, 'mtlk_serializer_init')
context = re.search(r'struct mtlk_scan_quiesce \{.*?\n\};', core, re.S).group()
functions = '\n'.join(extract(core, name) for name in
                      ('_mtlk_core_remove_scan', '_mtlk_core_remove_scan_done',
                       'mtlk_core_scan_quiesce'))
stop = extract(serializer, 'mtlk_serializer_stop')
invoke = extract(serializer, '_mtlk_serializer_invoke_command')

harness = r'''
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define __MTLK_IFUNC
#define MTLK_ASSERT(x) assert(x)
#define MTLK_ERR_OK 0
#define MTLK_ERR_NOT_READY -19
#define MTLK_ERR_NO_MEM -12
#define MTLK_SLID 0
#define TRUE 1
#define FALSE 0
#define ELOG_D(...) ((void)0)
#define HANDLE_T(x) ((mtlk_handle_t)(x))
#define _MTLK_CORE_PRIORITY_USER 3
#define MTLK_CMD_EXECUTED 1
#define MTLK_CMD_CANCELED 2
typedef int BOOL;
typedef uintptr_t mtlk_handle_t;
typedef int serializer_result_t;
struct completion { pthread_mutex_t mutex; pthread_cond_t cond; int done; };
static void init_completion(struct completion *c) {
  assert(!pthread_mutex_init(&c->mutex,NULL));
  assert(!pthread_cond_init(&c->cond,NULL)); c->done=0;
}
static void complete(struct completion *c) {
  pthread_mutex_lock(&c->mutex); c->done=1; pthread_cond_broadcast(&c->cond);
  pthread_mutex_unlock(&c->mutex);
}
static void wait_for_completion(struct completion *c) {
  pthread_mutex_lock(&c->mutex);
  while (!c->done) pthread_cond_wait(&c->cond,&c->mutex);
  pthread_mutex_unlock(&c->mutex);
  pthread_cond_destroy(&c->cond); pthread_mutex_destroy(&c->mutex);
}
typedef struct command {
  void (*cmd_callback)(mtlk_handle_t);
  mtlk_handle_t user_context;
  void (*post_exec_callback)(serializer_result_t,struct command *,mtlk_handle_t);
  mtlk_handle_t post_exec_callback_ctx;
  int is_cancelled;
} mtlk_command_t;
typedef struct {
  int stop_done,steps,osdep,tasks_pending_lock,lock;
  mtlk_command_t *current_command;
} mtlk_serializer_t;
/* This fixture models serializer locking; current-command reader races are
 * covered with pthread locks by serializer-current-lifetime.py. */
static void mtlk_osal_lock_acquire(int *lock) { (void)lock; }
static void mtlk_osal_lock_release(int *lock) { (void)lock; }
typedef struct { mtlk_serializer_t serializer; } slow_ctx_t;
typedef struct { slow_ctx_t *slow_ctx; } mtlk_core_t;
CONTEXT
static pthread_mutex_t queue_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t queue_cond=PTHREAD_COND_INITIALIZER;
static mtlk_command_t *queued;
static int fault, pending, active_scan, prevented, joins, stop_calls, command_cleanups;
static int closed, worker_started, release_worker, force_cancel;
static _Atomic int returned;
static int mtlk_command_init(mtlk_command_t *cmd,void (*fn)(mtlk_handle_t),
                              mtlk_handle_t ctx,int slid) {
  (void)slid;
  if (fault==1) return MTLK_ERR_NO_MEM;
  memset(cmd,0,sizeof(*cmd)); cmd->cmd_callback=fn; cmd->user_context=ctx; return 0;
}
static void mtlk_command_cleanup(mtlk_command_t *cmd) { (void)cmd; command_cleanups++; }
static int mtlk_serializer_enqueue(mtlk_serializer_t *s,unsigned priority,
    mtlk_command_t *cmd,void (*done)(serializer_result_t,mtlk_command_t *,mtlk_handle_t),
    mtlk_handle_t context) {
  assert(priority==_MTLK_CORE_PRIORITY_USER && closed);
  if (fault==2 || s->stop_done) return MTLK_ERR_NOT_READY;
  pthread_mutex_lock(&queue_lock);
  cmd->post_exec_callback=done; cmd->post_exec_callback_ctx=context;
  cmd->is_cancelled=force_cancel; queued=cmd;
  pthread_cond_broadcast(&queue_cond); pthread_mutex_unlock(&queue_lock); return 0;
}
static void abort_scan_sync(mtlk_core_t *c) {
  assert(c && closed && pending==0); active_scan=0;
}
static void pause_or_prevent_scan(mtlk_core_t *c) {
  assert(c && !active_scan); prevented=1;
}
/* Preserve the vendor lifecycle's strict step ordering and reject double stop. */
#define MTLK_OBJ_PTR(x) (x)
#define MTLK_STOP_BEGIN(m,o) do { assert((o)->steps==7); stop_calls++;
#define STEP_START_PROCESSING 4
#define STEP_SZR_OSDEP 2
#define STEP_TASKS_PENDING_LOCK 1
#define MTLK_STOP_STEP(m,s,o,fn,args) do { \
  assert((o)->steps==2*STEP_##s-1); fn args; (o)->steps &= ~STEP_##s; \
} while(0);
#define MTLK_STOP_END(m,o) assert((o)->steps==0); } while(0)
static void _mtlk_serializer_stop_processing(mtlk_serializer_t *s) {
  assert(s->steps==7);
  /* Accepted work must drain before the worker join and local cleanup. */
  pending=0;
}
static void _mtlk_serializer_osdep_stop(int *osdep) { (void)osdep; joins++; }
static void mtlk_rmlock_cleanup(int *lock) { (void)lock; }
STOP
INVOKE
FUNCTIONS
static slow_ctx_t slow;
static mtlk_core_t core={.slow_ctx=&slow};
static void *remover(void *unused) {
  (void)unused; mtlk_core_scan_quiesce(&core); returned=1; return NULL;
}
static void *worker(void *unused) {
  mtlk_command_t *cmd;
  (void)unused; pthread_mutex_lock(&queue_lock);
  while (!queued) pthread_cond_wait(&queue_cond,&queue_lock);
  worker_started=1; pthread_cond_broadcast(&queue_cond);
  while (!release_worker) pthread_cond_wait(&queue_cond,&queue_lock);
  cmd=queued; queued=NULL; pthread_mutex_unlock(&queue_lock);
  /* Two older same-priority requests execute before the barrier. */
  assert(pending==2); pending=0;
  if (force_cancel==2) cmd->post_exec_callback(MTLK_CMD_CANCELED,cmd,cmd->post_exec_callback_ctx);
  else {
    slow.serializer.current_command=cmd;
    _mtlk_serializer_invoke_command(&slow.serializer,cmd);
  }
  return NULL;
}
static void reset(void) {
  memset(&slow,0,sizeof(slow)); slow.serializer.steps=7;
  queued=NULL; fault=force_cancel=0; pending=2; active_scan=closed=1;
  prevented=joins=stop_calls=command_cleanups=worker_started=release_worker=returned=0;
}
int main(void) {
  for (int cancel=0; cancel<3; cancel++) {
    pthread_t r,w; reset(); force_cancel=cancel;
    assert(!pthread_create(&w,NULL,worker,NULL));
    assert(!pthread_create(&r,NULL,remover,NULL));
    pthread_mutex_lock(&queue_lock);
    while (!worker_started) pthread_cond_wait(&queue_cond,&queue_lock);
    assert(!returned && pending==2 && active_scan);
    release_worker=1; pthread_cond_broadcast(&queue_cond); pthread_mutex_unlock(&queue_lock);
    pthread_join(r,NULL); pthread_join(w,NULL);
    assert(returned && !pending && !active_scan && prevented && command_cleanups==1);
    assert(joins==(cancel==2));
    mtlk_serializer_stop(&slow.serializer); mtlk_serializer_stop(&slow.serializer);
    assert(joins==1 && stop_calls==1);
  }
  for (int fail=1; fail<=3; fail++) {
    reset(); fault=fail;
    if (fail==3) { mtlk_serializer_stop(&slow.serializer); }
    remover(NULL);
    assert(returned && !pending && !active_scan && prevented && joins==1);
    mtlk_serializer_stop(&slow.serializer);
    assert(joins==1 && stop_calls==1);
    assert(command_cleanups==(fail!=1));
  }
  puts("PASS: FIFO barrier, recovery cancellation flag, cancellation fallback, init/enqueue rejection, stopped serializer and repeated stop");
  return 0;
}
'''
for key, value in [('CONTEXT', context), ('STOP', stop), ('INVOKE', invoke), ('FUNCTIONS', functions)]:
    harness = harness.replace('\n' + key + '\n', '\n' + value + '\n')
with tempfile.TemporaryDirectory(prefix='wave-removal-barrier-') as directory:
    source = Path(directory) / 'probe.c'
    binary = Path(directory) / 'probe'
    source.write_text(harness)
    flags = ['-static'] if a.qemu else ['-fsanitize=address,undefined',
            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    subprocess.run([a.cc, '-std=gnu11', '-O1', '-g', '-pthread', '-Wall', '-Wextra',
                    '-Werror', '-Wno-unused-parameter', *flags, str(source), '-o', str(binary)], check=True)
    command = [str(binary)]
    if a.qemu:
        command.insert(0, str(a.qemu.resolve()))
    subprocess.run(command, check=True, timeout=30)
