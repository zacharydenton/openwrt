#!/usr/bin/env python3
"""Check worker creation failures with production start/stop and lifecycle macros."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tree', type=Path)
p.add_argument('--cc', default='cc')
p.add_argument('--qemu', type=Path)
p.add_argument('--expect-vulnerable', action='store_true')
p.add_argument('--output', type=Path)
a = p.parse_args()
driver = a.tree / 'wireless/driver/linux/mtlk_serializer_osdep.c'
shared = (a.tree / 'wireless/shared').resolve()
source = driver.read_text()
# Keep the entire OS-dependent implementation, including actual step lists.
source = re.sub(r'^#include .*\n', '', source, flags=re.M)
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define __MTLK_IFUNC
#define __INLINE inline
#define MTLK_ASSERT(x) assert(x)
#define MTLK_UNREFERENCED_PARAM(x) ((void)(x))
#define __UNLIKELY(x) (x)
#define TRUE 1
#define FALSE 0
#define MTLK_ERR_OK 0
#define MTLK_ERR_UNKNOWN -1
#define MTLK_ERR_NO_RESOURCES -5
#define MTLK_OSAL_EVENT_INFINITE 0
typedef uint32_t uint32;
typedef int BOOL;
typedef uintptr_t mtlk_handle_t;
#include "mtlkstartup.h"
int g_CurrentStepNumber;
void MTLK_STEPS_INFO_S(const char *s) { (void)s; }
void MTLK_STEPS_INFO_SD(const char *s,int n) { (void)s; (void)n; }
void MTLK_STEPS_INFO_SDD(const char *s,int n,int m) { (void)s; (void)n; (void)m; }
void MTLK_STEPS_WARNING_S(const char *s) { (void)s; }
void MTLK_STEPS_ERROR_S(const char *s) { (void)s; }
void MTLK_STEPS_ERROR_SD(const char *s,int n,void *v) { (void)s; (void)n; (void)v; }
struct task_struct { int live; };
typedef int mtlk_osal_event_t;
typedef void (*mtlk_szr_clb_t)(mtlk_handle_t);
typedef struct {
  mtlk_osal_event_t new_event;
  struct task_struct *thread;
  volatile BOOL stop;
  mtlk_szr_clb_t szr_clb;
  mtlk_handle_t szr_clb_ctx;
  MTLK_DECLARE_INIT_STATUS;
  MTLK_DECLARE_START_STATUS;
} mtlk_serializer_osdep_t;
static struct task_struct valid_task;
static int injected_error, starts, stops, invalid_stops, live_events;
/* Model Linux's ERR_PTR/IS_ERR encoding, not worker scheduling. */
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
static struct task_struct *kthread_run(int (*fn)(void *),void *ctx,const char *name) {
  assert(fn && ctx && name); starts++;
  if (injected_error) return (struct task_struct *)(intptr_t)-injected_error;
  assert(!valid_task.live); valid_task.live=1; return &valid_task;
}
static int kthread_stop(struct task_struct *task) {
  if (IS_ERR(task) || !task) { invalid_stops++; return 0; }
  assert(task==&valid_task && task->live); task->live=0; stops++; return 0;
}
static int kthread_should_stop(void) { return 1; }
static void schedule(void) {}
static int mtlk_osal_event_init(mtlk_osal_event_t *e) { *e=0; live_events++; return 0; }
static void mtlk_osal_event_cleanup(mtlk_osal_event_t *e) { (void)e; live_events--; }
static void mtlk_osal_event_reset(mtlk_osal_event_t *e) { *e=0; }
static void mtlk_osal_event_set(mtlk_osal_event_t *e) { *e=1; }
static void mtlk_osal_event_wait(mtlk_osal_event_t *e,int timeout) { (void)e; (void)timeout; }
void _mtlk_serializer_osdep_stop(mtlk_serializer_osdep_t *osdep);
void _mtlk_serializer_osdep_cleanup(mtlk_serializer_osdep_t *osdep);
void _mtlk_serializer_osdep_notify(mtlk_serializer_osdep_t *osdep);
SOURCE
static void callback(mtlk_handle_t context) { (void)context; }
int main(void) {
  int failures=0;
  for (int error=1; error<=4095; error++) {
    mtlk_serializer_osdep_t osdep;
    starts=stops=invalid_stops=0;
    assert(_mtlk_serializer_osdep_init(&osdep)==0);
    injected_error=error;
    int result=_mtlk_serializer_osdep_start(&osdep,"probe",callback,42);
    if (result==0) _mtlk_serializer_osdep_stop(&osdep);
    if (result!=MTLK_ERR_NO_RESOURCES || invalid_stops || stops) failures++;
    assert(starts==1 && !valid_task.live);
    /* A rejected start must leave the same object reusable. */
    injected_error=0;
    assert(_mtlk_serializer_osdep_start(&osdep,"retry",callback,43)==0);
    assert(osdep.thread==&valid_task && !osdep.stop && valid_task.live);
    _mtlk_serializer_osdep_stop(&osdep);
    assert(stops==1 && !valid_task.live);
    _mtlk_serializer_osdep_cleanup(&osdep);
    assert(live_events==0);
  }
  printf("{\"error_pointer_cases\":4095,\"successful_retries\":4095,\"unsafe_failures\":%d}\n",failures);
  return 0;
}
'''.replace('\nSOURCE\n', '\n' + source + '\n')
with tempfile.TemporaryDirectory(prefix='wave-thread-start-') as directory:
    probe = Path(directory) / 'probe.c'
    binary = Path(directory) / 'probe'
    probe.write_text(harness)
    flags = ['-static'] if a.qemu else ['-fsanitize=address,undefined',
            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    subprocess.run([a.cc, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    *flags, '-I', str(shared), str(probe), '-o', str(binary)], check=True)
    command = [str(binary)]
    if a.qemu:
        command.insert(0, str(a.qemu.resolve()))
    result = subprocess.run(command, check=True, text=True, capture_output=True, timeout=30)
    cases = json.loads(result.stdout)
report = {
    'schema': 1,
    'hardware_tested': False,
    'source_gate_passed': cases['unsafe_failures'] == 0,
    'historical_reproduction': a.expect_vulnerable,
    'scope': 'Production OS-dependent serializer functions and actual mtlkstartup/mtlkbfield headers; modeled kthread and event leaves, no Linux worker execution.',
    'source_sha256': {str(f.relative_to(a.tree.resolve())): hashlib.sha256(f.read_bytes()).hexdigest()
                      for f in (driver.resolve(), shared / 'mtlkstartup.h', shared / 'mtlkbfield.h')},
    'cases': cases,
    'runner': str(a.qemu.resolve()) if a.qemu else 'native ASan/UBSan',
}
if a.output:
    a.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
expected = 4095 if a.expect_vulnerable else 0
raise SystemExit(0 if cases['unsafe_failures'] == expected else 1)
