#!/usr/bin/env python3
"""Exercise the prepared VAP unpublish and tasklet drain order."""

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
    end = source.find("\n}", match.end())
    if end < 0:
        raise ValueError(f"end of {name}")
    return source[start : end + 2]


p = argparse.ArgumentParser(description=__doc__)
p.add_argument("tree", type=Path)
p.add_argument("--cc", default="cc")
p.add_argument("--qemu", type=Path)
a = p.parse_args()
vap = (a.tree / "wireless/driver/linux/mtlk_vap_manager.c").read_text()
drv = (a.tree / "wireless/driver/linux/mtlk_mmb_drv.c").read_text()
functions = "\n\n".join(
    [extract(vap, "__mtlk_vap_manager_vap_handle_by_id")]
    + [extract(drv, name) for name in ("mtlk_mmb_drv_vap_tasklets_pause", "mtlk_mmb_drv_vap_tasklets_resume")]
    + [extract(vap, "mtlk_vap_delete")]
)
code = r'''
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define __MTLK_IFUNC
#define __INLINE inline
#define __LIKELY(x) (x)
#define __UNLIKELY(x) (x)
#define MTLK_ASSERT(x) assert(x)
#define ELOG_D(fmt, x) fprintf(stderr, fmt "\n", x)
#define BIT(x) (1U << (x))
#define IRQS_TO_HANDLE 1
#define READ_ONCE(x) __atomic_load_n(&(x), __ATOMIC_ACQUIRE)
#define smp_load_acquire(p) __atomic_load_n((p), __ATOMIC_ACQUIRE)
#define smp_store_release(p,v) __atomic_store_n((p), (v), __ATOMIC_RELEASE)
#define container_of(ptr,type,field) ((type *)((char *)(ptr)-offsetof(type,field)))
typedef uint8_t uint8;
typedef uint32_t uint32;

struct mock_tasklet { pthread_mutex_t mutex; pthread_cond_t cond; int running, disabled; };
typedef struct mock_tasklet tasklet_struct;
static void tasklet_init(tasklet_struct *t) {
  pthread_mutex_init(&t->mutex, 0);
  pthread_cond_init(&t->cond, 0);
  t->running = t->disabled = 0;
}
static void tasklet_disable(tasklet_struct *t) {
  pthread_mutex_lock(&t->mutex);
  ++t->disabled;
  while (t->running) pthread_cond_wait(&t->cond, &t->mutex);
  pthread_mutex_unlock(&t->mutex);
}
static void tasklet_enable(tasklet_struct *t) {
  pthread_mutex_lock(&t->mutex);
  assert(t->disabled > 0);
  --t->disabled;
  pthread_mutex_unlock(&t->mutex);
}
typedef struct { int unused; } ccr_t;
typedef struct { int irq_no; } irq_data_t;
typedef struct _mtlk_mmb_drv_t {
  ccr_t ccr;
  int nof_irqs, tasklets_initialized;
  tasklet_struct irq_tasklet[IRQS_TO_HANDLE];
  tasklet_struct irq_tasklets_global[1];
  irq_data_t irq_handler_data[IRQS_TO_HANDLE];
  void *ihd_pending;
} mtlk_mmb_drv_t;
typedef struct { mtlk_mmb_drv_t *drv; } mtlk_hw_t;
typedef struct _mtlk_vap_manager_t mtlk_vap_manager_t;
typedef struct _mtlk_vap_handle_t {
  mtlk_vap_manager_t *manager;
  mtlk_hw_t *hw;
  uint8 id;
  uint32 magic;
} *mtlk_vap_handle_t;
struct _mtlk_vap_manager_t {
  struct _mtlk_vap_handle_t **guest_vap_array;
  uint32 max_vaps_count;
};
static ccr_t *mtlk_hw_mmb_get_ccr(mtlk_hw_t *h) { return &h->drv->ccr; }
static int _mmb_drv_is_irqno_required(mtlk_hw_t *h, int n) { (void)h; (void)n; return 1; }
static mtlk_vap_manager_t *mtlk_vap_get_manager(mtlk_vap_handle_t h) { return h->manager; }
static uint8 mtlk_vap_get_id(mtlk_vap_handle_t h) { return h->id; }
static mtlk_hw_t *mtlk_vap_get_hw(mtlk_vap_handle_t h) { return h->hw; }
static int cleanup_count;
static void _mtlk_vap_cleanup(mtlk_vap_handle_t h) {
  tasklet_struct *t = &h->hw->drv->irq_tasklet[0];
  pthread_mutex_lock(&t->mutex);
  assert(!t->running && t->disabled);
  pthread_mutex_unlock(&t->mutex);
  __atomic_add_fetch(&cleanup_count, 1, __ATOMIC_RELEASE);
}
static void mtlk_osal_mem_free(void *p) { free(p); }

ACTUAL_FUNCTIONS

static mtlk_vap_manager_t manager;
static tasklet_struct *tasklet;
static volatile int callback_started;
static volatile int release_callback;
static volatile int deletion_done;

static void *callback(void *unused) {
  mtlk_vap_handle_t h;
  (void)unused;
  pthread_mutex_lock(&tasklet->mutex);
  assert(!tasklet->disabled);
  tasklet->running = 1;
  pthread_mutex_unlock(&tasklet->mutex);
  h = __mtlk_vap_manager_vap_handle_by_id(&manager, 0);
  assert(h && h->magic == 0x12345678);
  WRITE_ONCE(callback_started, 1);
  while (!READ_ONCE(release_callback)) sched_yield();
  assert(h->magic == 0x12345678);
  pthread_mutex_lock(&tasklet->mutex);
  tasklet->running = 0;
  pthread_cond_broadcast(&tasklet->cond);
  pthread_mutex_unlock(&tasklet->mutex);
  return 0;
}
static void *deleter(void *data) {
  mtlk_vap_delete(data);
  WRITE_ONCE(deletion_done, 1);
  return 0;
}
int main(void) {
  mtlk_mmb_drv_t drv = {0};
  mtlk_hw_t hw = {.drv=&drv};
  struct _mtlk_vap_handle_t *slots[1];
  pthread_t reader, writer;
  drv.nof_irqs = 1;
  drv.tasklets_initialized = 1;
  tasklet_init(&drv.irq_tasklet[0]);
  tasklet = &drv.irq_tasklet[0];
  manager.guest_vap_array = slots;
  manager.max_vaps_count = 1;
  slots[0] = calloc(1, sizeof(*slots[0]));
  slots[0]->manager = &manager;
  slots[0]->hw = &hw;
  slots[0]->magic = 0x12345678;
  assert(pthread_create(&reader, 0, callback, 0) == 0);
  while (!READ_ONCE(callback_started)) sched_yield();
  assert(pthread_create(&writer, 0, deleter, slots[0]) == 0);
  for (int i=0; i<1000000 && smp_load_acquire(&slots[0]); ++i) sched_yield();
  assert(!smp_load_acquire(&slots[0]));
  assert(!READ_ONCE(deletion_done) && READ_ONCE(cleanup_count) == 0);
  WRITE_ONCE(release_callback, 1);
  assert(pthread_join(reader, 0) == 0);
  assert(pthread_join(writer, 0) == 0);
  assert(READ_ONCE(cleanup_count) == 1 && READ_ONCE(deletion_done));
  assert(!tasklet->disabled);
  puts("PASS: actual VAP delete unpublished before cleanup and drained an in-flight tasklet");
  return 0;
}
'''
# The mock uses atomics for the state flags shared by threads.
code = code.replace("#define READ_ONCE(x)", "#define WRITE_ONCE(x,v) __atomic_store_n(&(x), (v), __ATOMIC_RELEASE)\n#define READ_ONCE(x)")
code = code.replace("ACTUAL_FUNCTIONS", functions)
with tempfile.TemporaryDirectory(prefix="ax3000-vap-drain-") as temp:
    directory = Path(temp)
    (directory / "test.c").write_text(code)
    binary = directory / "test"
    command = [a.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pthread"]
    if a.qemu is None:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    else:
        command += ["-static"]
    command += [str(directory / "test.c"), "-o", str(binary)]
    subprocess.run(command, check=True)
    run = [str(binary)] if a.qemu is None else [str(a.qemu), str(binary)]
    subprocess.run(run, check=True)
