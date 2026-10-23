#!/usr/bin/env python3
"""Exercise the real asynchronous channel-request teardown admission gate."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('tree', type=Path)
parser.add_argument('--cc', default='gcc')
parser.add_argument('--qemu', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()

scan = (args.tree / 'wireless/driver/shared/scan_support.c').read_text()
core = (args.tree / 'wireless/driver/linux/core.c').read_text()


def extract(source, name):
    match = re.search(r'^(?:static\s+)?(?:BOOL|void|int)\s+(?:__MTLK_IFUNC\s+)?' +
                      name + r'\s*\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


gate = '\n\n'.join(extract(scan, name) for name in
                     ('scan_support_channel_request_enter',
                      'scan_support_channel_request_exit',
                      'scan_support_channel_requests_idle',
                      'scan_support_prepare_remove'))
switch = extract(core, '_mtlk_core_switch_channel_normal')
cac = extract(scan, 'cac_timer_serialized_func')
enter_at = cac.index('scan_support_channel_request_enter(ss)')
submit_at = cac.index('_mtlk_df_user_invoke_core_async', enter_at)
exit_at = cac.index('scan_support_channel_request_exit(ss)', submit_at)
assert enter_at < submit_at < exit_at

harness = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#define TRUE 1
#define FALSE 0
#define MTLK_ERR_OK 0
#define MTLK_ERR_NOT_READY -7
#define WAVE_RADIO_REQ_SET_CHAN 23
#define ST_NORMAL 3
#define __MTLK_IFUNC
#define ILOG0_V(...) ((void)0)
#define WARN_ON_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
typedef int BOOL;
typedef unsigned uint32;
typedef uintptr_t mtlk_handle_t;
typedef pthread_mutex_t spinlock_t;
typedef struct { int unused; } wait_queue_head_t;
#define spin_lock_init(lock) pthread_mutex_init((lock), NULL)
#define spin_lock_irqsave(lock, flags) do { (flags)=0; pthread_mutex_lock(lock); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); pthread_mutex_unlock(lock); } while (0)
#define init_waitqueue_head(wait) ((void)(wait))
#define wake_up_all(wait) ((void)(wait))
#define wait_event(wait, condition) do { (void)(wait); while (!(condition)) sched_yield(); } while (0)
typedef struct { unsigned armed; } mtlk_osal_timer_t;
struct mtlk_chan_def { unsigned center_freq1, width; };
struct net_device { unsigned live; };
struct set_chan_param_data {
  struct mtlk_chan_def chandef;
  struct net_device *ndev;
  int vap_id, switch_type, block_tx_pre, block_tx_post, radar_required;
};
struct slow_ctx { mtlk_osal_timer_t cac_timer, sched_scan_timer; };
struct mtlk_core;
typedef struct scan_support {
  struct mtlk_core *master_core;
  BOOL removal_pending;
  spinlock_t channel_req_lock;
  wait_queue_head_t channel_req_wait;
  unsigned channel_req_users;
} mtlk_scan_support_t;
typedef struct mtlk_core {
  void *vap_handle;
  struct slow_ctx *slow_ctx;
  mtlk_scan_support_t *scan;
} mtlk_core_t;
typedef struct { mtlk_core_t *core; } mtlk_vap_handle_obj;
typedef mtlk_vap_handle_obj *mtlk_vap_handle_t;
typedef struct { mtlk_vap_handle_t vap; } mtlk_df_t;
typedef struct { struct net_device *ndev; } mtlk_df_user_t;
typedef struct { int unused; } wave_radio_t;
static mtlk_scan_support_t ss;
static mtlk_core_t master;
static struct slow_ctx slow;
static mtlk_vap_handle_obj vap;
static mtlk_df_t df;
static mtlk_df_user_t user;
static struct net_device ndev;
static wave_radio_t radio;
static struct set_chan_param_data copied;
static unsigned queued, radar_released, timers_canceled;
static _Atomic int block_submit, submit_entered, allow_submit, closer_done;
static mtlk_scan_support_t *__wave_core_scan_support_get(mtlk_core_t *c) { return c->scan; }
static void *mtlk_vap_get_manager(void *handle) { return handle; }
static mtlk_df_t *mtlk_vap_manager_get_master_df(void *manager) { (void)manager; return &df; }
static mtlk_vap_handle_t mtlk_df_get_vap_handle(mtlk_df_t *d) { return d->vap; }
static int mtlk_vap_get_id(mtlk_vap_handle_t handle) { assert(handle == &vap); return 4; }
static mtlk_df_user_t *mtlk_df_get_user(mtlk_df_t *d) { assert(d == &df); return &user; }
static struct net_device *mtlk_df_user_get_ndev(mtlk_df_user_t *u) { return u->ndev; }
static void copy_mtlk_chandef(struct mtlk_chan_def *to, struct mtlk_chan_def *from) { *to = *from; }
static wave_radio_t *wave_vap_radio_get(void *handle) { (void)handle; return &radio; }
static void wave_radio_on_rcvry_isolate(wave_radio_t *r) { assert(r == &radio); radar_released++; }
static void mtlk_osal_timer_cancel_sync(mtlk_osal_timer_t *timer) {
  assert(radar_released); timer->armed = 0; timers_canceled++;
}
static void _mtlk_df_user_invoke_core_async(mtlk_df_t *d, unsigned request,
                                             const void *data, unsigned size,
                                             void *callback, mtlk_handle_t context) {
  (void)callback; (void)context;
  assert(d == &df && request == WAVE_RADIO_REQ_SET_CHAN);
  assert(size == sizeof(copied));
  submit_entered = 1;
  while (block_submit && !allow_submit) sched_yield();
  memcpy(&copied, data, size);
  queued++;
}
GATE
SWITCH
static void reset(void) {
  memset(&ss, 0, sizeof(ss)); memset(&master, 0, sizeof(master));
  memset(&slow, 0, sizeof(slow)); memset(&copied, 0, sizeof(copied));
  spin_lock_init(&ss.channel_req_lock);
  init_waitqueue_head(&ss.channel_req_wait);
  ndev.live=1; user.ndev=&ndev; df.vap=&vap; vap.core=&master;
  master.vap_handle=&vap; master.slow_ctx=&slow; master.scan=&ss; ss.master_core=&master;
  slow.cac_timer.armed=slow.sched_scan_timer.armed=1;
  queued=radar_released=timers_canceled=0;
  block_submit=submit_entered=allow_submit=closer_done=0;
}
static void *producer(void *unused) {
  struct mtlk_chan_def chandef={.center_freq1=5500,.width=80};
  (void)unused;
  assert(_mtlk_core_switch_channel_normal(&master,&chandef)==MTLK_ERR_OK);
  return NULL;
}
static void *closer(void *unused) {
  (void)unused; scan_support_prepare_remove(&ss); closer_done=1; return NULL;
}
int main(void) {
  struct mtlk_chan_def chandef={.center_freq1=5260,.width=40};
  reset();
  assert(_mtlk_core_switch_channel_normal(&master,&chandef)==MTLK_ERR_OK);
  assert(queued==1 && copied.ndev==&ndev && copied.vap_id==4);
  assert(copied.chandef.center_freq1==5260 && copied.switch_type==ST_NORMAL);
  assert(!ss.channel_req_users);

  reset(); scan_support_prepare_remove(&ss);
  assert(ss.removal_pending && radar_released==1 && timers_canceled==2);
  assert(_mtlk_core_switch_channel_normal(&master,&chandef)==MTLK_ERR_NOT_READY);
  assert(!queued && !ss.channel_req_users);

  reset(); block_submit=1;
  pthread_t submitter, teardown;
  assert(!pthread_create(&submitter,NULL,producer,NULL));
  while (!submit_entered) sched_yield();
  assert(ss.channel_req_users==1);
  assert(!pthread_create(&teardown,NULL,closer,NULL));
  usleep(20000);
  assert(ss.removal_pending && !closer_done);
  allow_submit=1;
  pthread_join(submitter,NULL); pthread_join(teardown,NULL);
  assert(closer_done && queued==1 && !ss.channel_req_users);
  assert(_mtlk_core_switch_channel_normal(&master,&chandef)==MTLK_ERR_NOT_READY);
  assert(queued==1);
  puts("PASS: async channel admission, rejection and admitted-producer drain");
  return 0;
}
'''.replace('\nGATE\n', '\n' + gate + '\n').replace('\nSWITCH\n', '\n' + switch + '\n')


def run(path):
    path.mkdir(parents=True, exist_ok=True)
    source = path / 'probe.c'
    binary = path / 'probe'
    source.write_text(harness)
    flags = ['-static'] if args.qemu else [
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    subprocess.run([args.cc, '-std=gnu11', '-O1', '-g', '-pthread',
                    '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    *flags, str(source), '-o', str(binary)], check=True)
    command = [str(binary)]
    if args.qemu:
        command.insert(0, str(args.qemu.resolve()))
    subprocess.run(command, check=True, cwd=path)


if args.output:
    run(args.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-channel-gate-') as tmp:
        run(Path(tmp))
