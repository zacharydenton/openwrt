#!/usr/bin/env python3
"""Execute the prepared request handoff functions with two real threads."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def extract(source: str, name: str) -> str:
    match = re.search(r"^" + re.escape(name) + r"\s*\(", source, re.M)
    if not match:
        raise ValueError(name)
    start = source.rfind("\n", 0, match.start() - 1) + 1
    end = source.find("\n}\n", match.end())
    if end < 0:
        raise ValueError(f"end of {name}")
    return source[start : end + 3]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree", type=Path)
parser.add_argument("--cc", default="cc")
parser.add_argument("--qemu", type=Path)
args = parser.parse_args()
source = (args.tree / "wireless/driver/linux/mtlk_df_linux.c").read_text()
struct = source[source.index("struct _mtlk_user_request_t\n{") :]
struct = struct[: struct.index("\n};") + 3]
names = [
    "mtlk_df_ui_req_complete",
    "mtlk_df_ui_req_execute_on_caller",
    "_mtlk_df_ui_waitable_req_init",
    "_mtlk_df_ui_req_cleanup",
    "_mtlk_df_ui_req_wait_completion",
]
functions = "\n\n".join(extract(source, name) for name in names)

harness = r'''
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define __MTLK_IFUNC
#define __INLINE inline
#define MTLK_ASSERT(x) assert(x)
#define MTLK_ERR_OK 0
#define MTLK_ERR_PARAMS -22
#define MTLK_OSAL_EVENT_INFINITE UINT32_MAX
#define TRUE 1
#define FALSE 0
#define READ_ONCE(x) __atomic_load_n(&(x), __ATOMIC_ACQUIRE)
#define WRITE_ONCE(x, v) __atomic_store_n(&(x), (v), __ATOMIC_RELEASE)
typedef int BOOL;
typedef uint32_t uint32;
typedef uintptr_t mtlk_handle_t;
typedef struct {
  pthread_mutex_t mutex;
  pthread_cond_t cond;
  int flag;
} mtlk_osal_event_t;
typedef struct _mtlk_user_request_t mtlk_user_request_t;
typedef void (*_req_notify_clb_t)(mtlk_handle_t);
typedef int (*mtlk_df_ui_caller_func_t)(mtlk_handle_t, const void *, uint32);

static int mtlk_osal_event_init(mtlk_osal_event_t *e) {
  assert(pthread_mutex_init(&e->mutex, 0) == 0);
  assert(pthread_cond_init(&e->cond, 0) == 0);
  e->flag = 0;
  return MTLK_ERR_OK;
}
static int mtlk_osal_event_wait(mtlk_osal_event_t *e, uint32 timeout) {
  assert(timeout == MTLK_OSAL_EVENT_INFINITE);
  pthread_mutex_lock(&e->mutex);
  while (!e->flag) pthread_cond_wait(&e->cond, &e->mutex);
  pthread_mutex_unlock(&e->mutex);
  return MTLK_ERR_OK;
}
static void mtlk_osal_event_set(mtlk_osal_event_t *e) {
  pthread_mutex_lock(&e->mutex);
  e->flag = 1;
  pthread_cond_broadcast(&e->cond);
  pthread_mutex_unlock(&e->mutex);
}
static void mtlk_osal_event_reset(mtlk_osal_event_t *e) {
  pthread_mutex_lock(&e->mutex);
  e->flag = 0;
  pthread_mutex_unlock(&e->mutex);
}
static void mtlk_osal_event_cleanup(mtlk_osal_event_t *e) {
  assert(pthread_cond_destroy(&e->cond) == 0);
  assert(pthread_mutex_destroy(&e->mutex) == 0);
}

REQUEST_STRUCT

REQUEST_FUNCTIONS

static pthread_t owner;
static int calls;
static int callback(mtlk_handle_t object, const void *data, uint32 size) {
  assert(pthread_equal(pthread_self(), owner));
  assert(size == sizeof(int));
  ++calls;
  return (int)object + *(const int *)data;
}
static void *worker(void *arg) {
  mtlk_user_request_t *req = arg;
  const int first = 7, second = 11;
  int a = mtlk_df_ui_req_execute_on_caller(req, callback, 5, &first, sizeof(first));
  int b = mtlk_df_ui_req_execute_on_caller(req, callback, 5, &second, sizeof(second));
  mtlk_df_ui_req_complete(req, a + b);
  return 0;
}
static void *complete_only(void *arg) {
  mtlk_df_ui_req_complete(arg, 42);
  return 0;
}
int main(void) {
  owner = pthread_self();
  for (int i = 0; i < 100; ++i) {
    mtlk_user_request_t req;
    pthread_t thread;
    memset(&req, 0, sizeof(req));
    assert(_mtlk_df_ui_waitable_req_init(&req) == MTLK_ERR_OK);
    assert(pthread_create(&thread, 0, worker, &req) == 0);
    assert(_mtlk_df_ui_req_wait_completion(&req) == MTLK_ERR_OK);
    assert(pthread_join(thread, 0) == 0);
    assert(req.result == 28);
    _mtlk_df_ui_req_cleanup(&req);
  }
  assert(calls == 200);
  {
    mtlk_user_request_t req;
    pthread_t thread;
    memset(&req, 0, sizeof(req));
    assert(_mtlk_df_ui_waitable_req_init(&req) == MTLK_ERR_OK);
    assert(pthread_create(&thread, 0, complete_only, &req) == 0);
    assert(_mtlk_df_ui_req_wait_completion(&req) == MTLK_ERR_OK);
    assert(pthread_join(thread, 0) == 0);
    assert(req.result == 42);
    _mtlk_df_ui_req_cleanup(&req);
  }
  {
    mtlk_user_request_t req;
    memset(&req, 0, sizeof(req));
    assert(mtlk_df_ui_req_execute_on_caller(&req, callback, 5, 0, 0) == MTLK_ERR_PARAMS);
  }
  puts("PASS: actual handoff functions preserve caller thread, two-step ordering and completion");
  return 0;
}
'''
code = harness.replace("REQUEST_STRUCT", struct).replace("REQUEST_FUNCTIONS", functions)
with tempfile.TemporaryDirectory(prefix="ax3000-rtnl-handoff-") as temp:
    path = Path(temp)
    (path / "handoff.c").write_text(code)
    binary = path / "handoff"
    command = [args.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pthread"]
    if args.qemu is None:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    else:
        command += ["-static"]
    command += [str(path / "handoff.c"), "-o", str(binary)]
    subprocess.run(command, check=True)
    run = [str(binary)] if args.qemu is None else [str(args.qemu), str(binary)]
    subprocess.run(run, check=True)
