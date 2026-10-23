#!/usr/bin/env python3
"""Exercise the prepared recovery/VAP admission functions in both race orders."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def extract(source: str, name: str) -> str:
    match = re.search(
        r"^(?:static\s+)?(?:int|void)\s+" + re.escape(name) +
        r"\s*\([^;]*?\)\s*\{", source, re.M | re.S
    )
    if not match:
        raise ValueError(name)
    start = match.start()
    end = source.find("\n}", match.end())
    if end < 0:
        raise ValueError("unterminated " + name)
    return source[start : end + 2]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree", type=Path)
parser.add_argument("--cc", default="cc")
parser.add_argument("--qemu", type=Path)
args = parser.parse_args()
recovery = (args.tree / "wireless/driver/shared/fw_recovery.c").read_text()
core = (args.tree / "wireless/driver/linux/core.c").read_text()
for request, handler in (
    ("ADD_VAP_IDX", "add_vap_idx"),
    ("ADD_VAP_NAME", "add_vap_name"),
    ("DEL_VAP_IDX", "del_vap_idx"),
    ("DEL_VAP_NAME", "del_vap_name"),
):
    if not re.search(
        r"_MTLK_CORE_HANDLE_REQ_SERIALIZABLE\(WAVE_RADIO_REQ_MBSS_" + request +
        r",\s*_mtlk_core_" + handler + r"_guarded\)", core
    ):
        raise ValueError("unguarded MBSS request: " + request)
functions = "\n\n".join(
    extract(recovery, name)
    for name in ("wave_rcvry_vap_change_begin", "wave_rcvry_vap_change_end", "_rcvry_task_initiate")
) + "\n\n" + extract(core, "_mtlk_core_vap_change_guard")

code = r'''
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define MTLK_ASSERT(x) assert(x)
#define MTLK_ERR_OK 0
#define MTLK_ERR_RETRY (-11)
#define RCVRY_TYPE_UNDEF 0
#define RCVRY_TYPE_ACTIVE 1
#define TRUE 1
#define FALSE 0
#define HANDLE_T_PTR(type, value) ((type *)(value))
#define atomic_read(value) atomic_load(value)
typedef int BOOL;
typedef uint32_t uint32;
typedef void *mtlk_handle_t;
typedef pthread_mutex_t mtlk_osal_mutex_t;
typedef struct { mtlk_osal_mutex_t vap_change_mutex; atomic_int is_mac_fatal_pending;
                 int signature, type; } wave_rcvry_task_ctx_t;
typedef struct { wave_rcvry_task_ctx_t rcvry_ctx; } wave_rcvry_card_cfg_t;
typedef struct { wave_rcvry_card_cfg_t *pcard; } mtlk_hw_t;
typedef struct { mtlk_hw_t *hw; } vap_handle_t;
typedef struct { vap_handle_t *vap_handle; } mtlk_core_t;
typedef struct { int result; } mtlk_clpb_t;
typedef int (*mtlk_core_task_func_t)(mtlk_handle_t, const void *, uint32);

static mtlk_hw_t hw;
static vap_handle_t master_vap = { .hw = &hw };
static mtlk_core_t master_core = { .vap_handle = &master_vap };
static int *dynamic_vap;
static int *snapshot;
static int mutations, recovery_schedules;
static int mode, handler_entered, allow_handler_exit, recovery_entered;
static int allow_recovery_exit, recovery_attempted, delete_attempted;
static pthread_mutex_t sync_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t sync_cond = PTHREAD_COND_INITIALIZER;
enum { NORMAL, DELETE_FIRST, RECOVERY_FIRST };

static wave_rcvry_task_ctx_t *_rcvry_task_ctx_get(const mtlk_hw_t *value) {
  return &value->pcard->rcvry_ctx;
}
static int _rcvry_is_initialized(wave_rcvry_task_ctx_t *ctx) { return ctx->signature == 42; }
static int __rcvry_type_current_get(wave_rcvry_task_ctx_t *ctx) { return ctx->type; }
static void mtlk_osal_mutex_acquire(mtlk_osal_mutex_t *mutex) {
  assert(pthread_mutex_lock(mutex) == 0);
}
static void mtlk_osal_mutex_release(mtlk_osal_mutex_t *mutex) {
  assert(pthread_mutex_unlock(mutex) == 0);
}
static mtlk_hw_t *mtlk_vap_get_hw(vap_handle_t *handle) { return handle->hw; }
static int mtlk_clpb_push_res(mtlk_clpb_t *clpb, int result) {
  clpb->result = result;
  return MTLK_ERR_OK;
}
static int __rcvry_task_initiate(wave_rcvry_card_cfg_t *pcard) {
  assert(pcard == hw.pcard);
  pcard->rcvry_ctx.type = RCVRY_TYPE_ACTIVE;
  snapshot = dynamic_vap;
  if (snapshot) assert(*snapshot == 7);
  ++recovery_schedules;
  if (mode == RECOVERY_FIRST) {
    pthread_mutex_lock(&sync_lock);
    recovery_entered = 1;
    pthread_cond_broadcast(&sync_cond);
    while (!allow_recovery_exit) pthread_cond_wait(&sync_cond, &sync_lock);
    pthread_mutex_unlock(&sync_lock);
  }
  return MTLK_ERR_OK;
}

ACTUAL_FUNCTIONS

static int delete_handler(mtlk_handle_t object, const void *data, uint32 size) {
  (void)object; (void)data; (void)size;
  if (mode == DELETE_FIRST) {
    pthread_mutex_lock(&sync_lock);
    handler_entered = 1;
    pthread_cond_broadcast(&sync_cond);
    while (!allow_handler_exit) pthread_cond_wait(&sync_cond, &sync_lock);
    pthread_mutex_unlock(&sync_lock);
  }
  assert(dynamic_vap && *dynamic_vap == 7);
  free(dynamic_vap);
  dynamic_vap = NULL;
  ++mutations;
  return MTLK_ERR_OK;
}
static int delete_request(void) {
  mtlk_clpb_t clpb = { .result = 99 };
  mtlk_clpb_t *ptr = &clpb;
  int res = _mtlk_core_vap_change_guard(&master_core, &ptr, sizeof(ptr), delete_handler);
  assert(res == MTLK_ERR_OK);
  return clpb.result;
}
static void *delete_thread(void *unused) {
  (void)unused;
  pthread_mutex_lock(&sync_lock);
  delete_attempted = 1;
  pthread_cond_broadcast(&sync_cond);
  pthread_mutex_unlock(&sync_lock);
  return (void *)(intptr_t)delete_request();
}
static void *recovery_thread(void *unused) {
  (void)unused;
  pthread_mutex_lock(&sync_lock);
  recovery_attempted = 1;
  pthread_cond_broadcast(&sync_cond);
  pthread_mutex_unlock(&sync_lock);
  assert(_rcvry_task_initiate(hw.pcard) == MTLK_ERR_OK);
  return NULL;
}
static void wait_for(int *flag) {
  pthread_mutex_lock(&sync_lock);
  while (!*flag) pthread_cond_wait(&sync_cond, &sync_lock);
  pthread_mutex_unlock(&sync_lock);
}

int main(void) {
  wave_rcvry_card_cfg_t card = {0};
  pthread_t deleter, recoverer;
  void *result;
  hw.pcard = &card;
  card.rcvry_ctx.signature = 42;
  assert(pthread_mutex_init(&card.rcvry_ctx.vap_change_mutex, NULL) == 0);

  mode = DELETE_FIRST;
  dynamic_vap = malloc(sizeof(*dynamic_vap));
  assert(dynamic_vap); *dynamic_vap = 7;
  assert(pthread_create(&deleter, NULL, delete_thread, NULL) == 0);
  wait_for(&handler_entered);
  assert(pthread_create(&recoverer, NULL, recovery_thread, NULL) == 0);
  wait_for(&recovery_attempted);
  pthread_mutex_lock(&sync_lock);
  allow_handler_exit = 1;
  pthread_cond_broadcast(&sync_cond);
  pthread_mutex_unlock(&sync_lock);
  assert(pthread_join(deleter, &result) == 0);
  assert((intptr_t)result == 99);
  assert(pthread_join(recoverer, NULL) == 0);
  assert(snapshot == NULL && dynamic_vap == NULL && mutations == 1);

  card.rcvry_ctx.type = RCVRY_TYPE_UNDEF;
  recovery_entered = allow_recovery_exit = delete_attempted = 0;
  mode = RECOVERY_FIRST;
  dynamic_vap = malloc(sizeof(*dynamic_vap));
  assert(dynamic_vap); *dynamic_vap = 7;
  assert(pthread_create(&recoverer, NULL, recovery_thread, NULL) == 0);
  wait_for(&recovery_entered);
  assert(pthread_create(&deleter, NULL, delete_thread, NULL) == 0);
  wait_for(&delete_attempted);
  pthread_mutex_lock(&sync_lock);
  allow_recovery_exit = 1;
  pthread_cond_broadcast(&sync_cond);
  pthread_mutex_unlock(&sync_lock);
  assert(pthread_join(recoverer, NULL) == 0);
  assert(pthread_join(deleter, &result) == 0);
  assert((intptr_t)result == MTLK_ERR_RETRY);
  assert(snapshot == dynamic_vap && mutations == 1 && recovery_schedules == 2);

  card.rcvry_ctx.type = RCVRY_TYPE_UNDEF;
  mode = NORMAL;
  atomic_store(&card.rcvry_ctx.is_mac_fatal_pending, 1);
  assert(delete_request() == MTLK_ERR_RETRY);
  assert(dynamic_vap && mutations == 1);
  atomic_store(&card.rcvry_ctx.is_mac_fatal_pending, 0);
  assert(delete_request() == 99);
  assert(dynamic_vap == NULL && mutations == 2);
  assert(pthread_mutex_destroy(&card.rcvry_ctx.vap_change_mutex) == 0);
  puts("PASS: VAP delete and recovery snapshot serialize in both orders");
  return 0;
}
'''.replace("ACTUAL_FUNCTIONS", functions)

with tempfile.TemporaryDirectory(prefix="ax3000-recovery-vap-") as directory:
    source = Path(directory) / "recovery-vap.c"
    binary = Path(directory) / "recovery-vap"
    source.write_text(code)
    command = [args.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pthread"]
    command += ["-static"] if args.qemu else ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    command += [str(source), "-o", str(binary)]
    subprocess.run(command, check=True)
    subprocess.run([str(args.qemu), str(binary)] if args.qemu else [str(binary)], check=True)
