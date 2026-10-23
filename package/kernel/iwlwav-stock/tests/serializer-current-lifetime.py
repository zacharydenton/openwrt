#!/usr/bin/env python3
"""Pause actual command completion after free, then enumerate on another thread."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def extract(source, name):
    match = re.search(r'^(?:static\s+)?(?:void|int|BOOL)\s+(?:__MTLK_IFUNC\s+)?' +
                      name + r'\s*\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tree', type=Path)
p.add_argument('--cc', default='cc')
p.add_argument('--qemu', type=Path)
p.add_argument('--expect-vulnerable', action='store_true')
p.add_argument('--output', type=Path)
a = p.parse_args()
serializer_path = a.tree / 'wireless/driver/shared/mtlk_serializer.c'
core_path = a.tree / 'wireless/driver/linux/core.c'
serializer = serializer_path.read_text()
core = core_path.read_text()
assert '_MTLK_CORE_HANDLE_REQ_SYNCHRONOUS(WAVE_CORE_REQ_GET_SERIALIZER_INFO,' in core
functions = '\n'.join(extract(serializer, name) for name in
    ('mtlk_serializer_enqueue', '_mtlk_serializer_invoke_command',
     '_mtlk_serializer_process_commands', 'mtlk_serializer_enum_commands'))
completion = extract(core, '_mtlk_core_async_compl_clb')
harness = r'''
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#define __MTLK_IFUNC
#define MTLK_ASSERT(x) assert(x)
#define ELOG_V(...) ((void)0)
#define TRUE 1
#define FALSE 0
#define MTLK_ERR_OK 0
#define MTLK_ERR_UNKNOWN -1
#define MTLK_ERR_NOT_READY -2
#define MTLK_ERR_BUSY -3
#define MTLK_CMD_EXECUTED 1
typedef int BOOL;
typedef unsigned uint32;
typedef uintptr_t mtlk_handle_t;
typedef int serializer_result_t;
typedef struct entry { struct entry *next,*prev; } mtlk_dlist_entry_t;
typedef mtlk_dlist_entry_t mtlk_dlist_t;
static void list_init(mtlk_dlist_t *h) { h->next=h->prev=h; }
static void mtlk_dlist_push_back(mtlk_dlist_t *h,mtlk_dlist_entry_t *e) {
  e->next=h; e->prev=h->prev; h->prev->next=e; h->prev=e;
}
static mtlk_dlist_entry_t *mtlk_dlist_pop_front(mtlk_dlist_t *h) {
  if (h->next==h) return NULL;
  mtlk_dlist_entry_t *e=h->next; h->next=e->next; e->next->prev=h; return e;
}
#define mtlk_dlist_foreach(list,entry,head) \
  for ((head)=(list),(entry)=(head)->next;(entry)!=(head);(entry)=(entry)->next)
#define MTLK_LIST_GET_CONTAINING_RECORD(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
typedef struct command {
  mtlk_dlist_entry_t list_entry;
  BOOL is_in_queue;
  uint32 priority, issuer_slid;
  void (*cmd_callback)(mtlk_handle_t);
  mtlk_handle_t user_context;
  void (*post_exec_callback)(serializer_result_t,struct command *,mtlk_handle_t);
  mtlk_handle_t post_exec_callback_ctx;
} mtlk_command_t;
typedef void (*mtlk_cmd_completion_clb_t)(serializer_result_t,mtlk_command_t *,mtlk_handle_t);
typedef struct {
  pthread_mutex_t lock;
  BOOL is_running;
  uint32 num_priorities;
  int tasks_pending_lock, osdep;
  mtlk_dlist_t commands[2];
  mtlk_command_t *current_command;
} mtlk_serializer_t;
typedef BOOL (*mtlk_serializer_enum_commands_f)(mtlk_serializer_t *,const mtlk_command_t *,BOOL,mtlk_handle_t);
typedef struct { mtlk_command_t cmd; } _core_async_exec_t;
static void mtlk_osal_lock_acquire(pthread_mutex_t *m) { assert(!pthread_mutex_lock(m)); }
static void mtlk_osal_lock_release(pthread_mutex_t *m) { assert(!pthread_mutex_unlock(m)); }
static void mtlk_rmlock_acquire(int *r) { ++*r; }
static void mtlk_rmlock_release(int *r) { assert(*r>0); --*r; }
static void _mtlk_serializer_osdep_notify(int *o) { ++*o; }
static pthread_mutex_t rendezvous=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static int freed_count, inspected_count, cleanups, bodies, stale_observations;
static uintptr_t freed_commands[2];
static mtlk_serializer_t serializer;
static void mtlk_command_cleanup(mtlk_command_t *cmd) {
  assert(!cmd->is_in_queue); cleanups++;
}
static void mtlk_osal_mem_free(void *p) {
  /* Real free, followed by a deterministic pause inside the actual completion.
   * The observer compares numeric addresses before touching any command. */
  uintptr_t address=(uintptr_t)&((_core_async_exec_t *)p)->cmd;
  free(p);
  pthread_mutex_lock(&rendezvous);
  assert(freed_count<2); freed_commands[freed_count++]=address;
  pthread_cond_broadcast(&changed);
  while (inspected_count<freed_count) pthread_cond_wait(&changed,&rendezvous);
  pthread_mutex_unlock(&rendezvous);
}
COMPLETION
FUNCTIONS
struct snapshot { int current,queued,stale,limit; };
static BOOL observe(mtlk_serializer_t *s,const mtlk_command_t *cmd,BOOL current,mtlk_handle_t ctx) {
  struct snapshot *snapshot=(struct snapshot *)ctx;
  assert(s==&serializer);
  for (int i=0;i<freed_count;i++) {
    if ((uintptr_t)cmd==freed_commands[i]) { snapshot->stale++; return TRUE; }
  }
  assert(cmd->issuer_slid==101 || cmd->issuer_slid==102);
  assert(cmd->priority<2);
  if (current) { snapshot->current++; assert(!cmd->is_in_queue); }
  else { snapshot->queued++; assert(cmd->is_in_queue); }
  return !snapshot->limit || snapshot->current+snapshot->queued<snapshot->limit;
}
static struct snapshot snapshot(int limit) {
  struct snapshot result={.limit=limit};
  mtlk_serializer_enum_commands(&serializer,observe,(mtlk_handle_t)&result);
  return result;
}
static void body(mtlk_handle_t context) {
  mtlk_command_t *cmd=(mtlk_command_t *)context;
  /* Higher priority executes first; the running command stays visible. */
  assert(cmd->issuer_slid==(bodies==0?102:101));
  struct snapshot state=snapshot(0);
  assert(state.current==1 && state.queued==1-bodies && !state.stale);
  state=snapshot(1);
  assert(state.current==1 && state.queued==0 && !state.stale);
  bodies++;
}
static void *worker(void *unused) {
  (void)unused; _mtlk_serializer_process_commands((mtlk_handle_t)&serializer); return NULL;
}
int main(void) {
  pthread_t task;
  assert(!pthread_mutex_init(&serializer.lock,NULL));
  serializer.is_running=TRUE; serializer.num_priorities=2;
  for (int i=0;i<2;i++) {
    list_init(&serializer.commands[i]);
    _core_async_exec_t *ctx=calloc(1,sizeof(*ctx)); assert(ctx);
    ctx->cmd.issuer_slid=101+i; ctx->cmd.cmd_callback=body;
    ctx->cmd.user_context=(mtlk_handle_t)&ctx->cmd;
    assert(mtlk_serializer_enqueue(&serializer,i,&ctx->cmd,
            _mtlk_core_async_compl_clb,(mtlk_handle_t)ctx)==0);
  }
  struct snapshot state=snapshot(0);
  assert(state.current==0 && state.queued==2 && !state.stale);
  state=snapshot(1); assert(state.queued==1 && !state.current && !state.stale);
  assert(!pthread_create(&task,NULL,worker,NULL));
  pthread_mutex_lock(&rendezvous);
  for (int completed=1;completed<=2;completed++) {
    while (freed_count<completed) pthread_cond_wait(&changed,&rendezvous);
    state=snapshot(0);
    assert(state.current==0 && state.queued==2-completed);
    stale_observations+=state.stale;
    inspected_count=completed; pthread_cond_broadcast(&changed);
  }
  pthread_mutex_unlock(&rendezvous);
  assert(!pthread_join(task,NULL));
  state=snapshot(0); assert(!state.current && !state.queued && !state.stale);
  assert(bodies==2 && cleanups==2 && !serializer.current_command);
  assert(!serializer.tasks_pending_lock);
  pthread_mutex_destroy(&serializer.lock);
  printf("{\"completed_commands\":2,\"freed_command_observations\":%d}\n",stale_observations);
  return 0;
}
'''
harness = harness.replace('\nCOMPLETION\n', '\n' + completion + '\n')
harness = harness.replace('\nFUNCTIONS\n', '\n' + functions + '\n')
with tempfile.TemporaryDirectory(prefix='wave-current-lifetime-') as directory:
    probe = Path(directory) / 'probe.c'
    binary = Path(directory) / 'probe'
    probe.write_text(harness)
    flags = ['-static'] if a.qemu else ['-fsanitize=address,undefined',
            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    subprocess.run([a.cc, '-std=gnu11', '-O1', '-g', '-pthread', '-Wall', '-Wextra',
                    '-Werror', '-Wno-unused-parameter', *flags, str(probe), '-o', str(binary)], check=True)
    command = [str(binary)]
    if a.qemu:
        command.insert(0, str(a.qemu.resolve()))
    result = subprocess.run(command, check=True, text=True, capture_output=True, timeout=30)
    cases = json.loads(result.stdout)
report = {
    'schema': 1,
    'hardware_tested': False,
    'source_gate_passed': cases['freed_command_observations'] == 0,
    'historical_reproduction': a.expect_vulnerable,
    'scope': 'Actual enqueue, worker loop, invocation, enumeration and core completion; pthread locks, real free and a rendezvous model the kernel scheduling interleaving. No target kernel execution.',
    'source_sha256': {str(f.relative_to(a.tree)): hashlib.sha256(f.read_bytes()).hexdigest()
                      for f in (serializer_path, core_path)},
    'cases': cases,
    'runner': str(a.qemu.resolve()) if a.qemu else 'native ASan/UBSan',
}
if a.output:
    a.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
expected = 2 if a.expect_vulnerable else 0
raise SystemExit(0 if cases['freed_command_observations'] == expected else 1)
