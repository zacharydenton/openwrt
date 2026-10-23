#!/usr/bin/env python3
"""Fault-inject VAP creation after DF/netdev setup using the prepared function."""

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
        raise ValueError(f"unterminated {name}")
    return source[start : end + 2]


p = argparse.ArgumentParser(description=__doc__)
p.add_argument("tree", type=Path)
p.add_argument("--cc", default="cc")
p.add_argument("--qemu", type=Path)
a = p.parse_args()
source = (a.tree / "wireless/driver/linux/mtlk_vap_manager.c").read_text()
function = extract(source, "mtlk_vap_manager_create_vap")
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define __MTLK_IFUNC
#define MTLK_ASSERT(x) assert(x)
#define MTLK_ERR_OK 0
#define MTLK_ERR_NO_MEM (-12)
#define MTLK_VAP_INVALID_IDX (-22)
#define MTLK_INVALID_VAP_HANDLE NULL
#define MTLK_MEM_TAG_VAP_NODE 1
#define ELOG_V(x) ((void)0)
#define ELOG_D(fmt,x) ((void)(x))
#define ELOG_DD(fmt,x,y) ((void)(x),(void)(y))
#define ELOG_DDD(fmt,x,y,z) ((void)(x),(void)(y),(void)(z))
#define smp_store_release(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
typedef uint8_t uint8;
typedef int BOOL;
typedef int mtlk_work_role_e;
struct net_device { int dummy; };
typedef struct _mtlk_vap_handle_t {
  uint8 id;
  int stage;
  int registered_netdev;
  int master;
} *mtlk_vap_handle_t;
typedef struct {
  struct _mtlk_vap_handle_t **guest_vap_array;
  int max_vaps_count;
} mtlk_vap_manager_t;

static int fault_stage;
static int cleanup_calls, free_calls, start_calls, delete_calls;
static int live_netdevs;
static mtlk_vap_manager_t *current_manager;
static int mtlk_vap_manager_prepare_vaps(mtlk_vap_manager_t *o) { (void)o; abort(); }
static mtlk_vap_handle_t __mtlk_vap_manager_vap_handle_by_id(mtlk_vap_manager_t *o, uint8 i) {
  return o->guest_vap_array[i];
}
static void *mtlk_osal_mem_alloc(size_t size, int tag) { (void)tag; return calloc(1,size); }
static void mtlk_osal_mem_free(void *p) {
  mtlk_vap_handle_t h=p;
  assert(h->stage == 0 && h->registered_netdev == 0);
  ++free_calls;
  free(p);
}
static int _mtlk_vap_init(mtlk_vap_handle_t h, mtlk_vap_manager_t *o, uint8 i,
                          void *ctx, const char *name, mtlk_work_role_e role,
                          BOOL master, struct net_device *ndev) {
  (void)o; (void)ctx; (void)name; (void)role; (void)ndev;
  if (fault_stage == 1) return -11;
  h->id=i; h->master=master; h->stage=1; h->registered_netdev=1;
  ++live_netdevs;
  return MTLK_ERR_OK;
}
static void _mtlk_vap_cleanup(mtlk_vap_handle_t h) {
  assert(h->stage == 1 && h->registered_netdev == 1);
  h->stage=0; h->registered_netdev=0;
  --live_netdevs;
  ++cleanup_calls;
}
static int _wave_vap_manager_txmm_txdm_set(mtlk_vap_handle_t h) {
  assert(h->stage == 1);
  return fault_stage == 2 ? -5 : MTLK_ERR_OK;
}
static int mtlk_vap_is_master(mtlk_vap_handle_t h) { return h->master; }
static int mtlk_vap_is_dut(mtlk_vap_handle_t h) { (void)h; return 0; }
static int mtlk_vap_get_oid(mtlk_vap_handle_t h) { return h->id; }
static int mtlk_vap_start(mtlk_vap_handle_t h) {
  assert(h->stage == 1);
  ++start_calls;
  return fault_stage == 3 ? -6 : MTLK_ERR_OK;
}
static void mtlk_vap_delete(mtlk_vap_handle_t h) {
  ++delete_calls;
  assert(current_manager->guest_vap_array[h->id] == h);
  current_manager->guest_vap_array[h->id] = NULL;
  _mtlk_vap_cleanup(h);
  free(h);
}

ACTUAL_FUNCTION

int main(void) {
  struct _mtlk_vap_handle_t *slots[2] = {0};
  mtlk_vap_manager_t manager = {.guest_vap_array=slots,.max_vaps_count=2};
  current_manager=&manager;
  for (fault_stage=1; fault_stage<=3; ++fault_stage) {
    int before_cleanup=cleanup_calls, before_free=free_calls;
    int res=mtlk_vap_manager_create_vap(&manager,1,0,"wlan1",1,0,0);
    assert(res != MTLK_ERR_OK);
    assert(slots[1] == NULL && live_netdevs == 0);
    assert(cleanup_calls-before_cleanup == (fault_stage == 1 ? 0 : 1));
    assert(free_calls-before_free == (fault_stage == 3 ? 0 : 1));
  }
  fault_stage=0;
  assert(mtlk_vap_manager_create_vap(&manager,1,0,"wlan1",1,0,0)==MTLK_ERR_OK);
  assert(slots[1] && live_netdevs == 1);
  _mtlk_vap_cleanup(slots[1]);
  mtlk_osal_mem_free(slots[1]);
  slots[1]=NULL;
  assert(live_netdevs == 0 && start_calls == 2 && delete_calls == 1);
  puts("PASS: actual VAP create rolls back registered netdev before freeing the handle");
  return 0;
}
'''.replace("ACTUAL_FUNCTION", function)
with tempfile.TemporaryDirectory(prefix="ax3000-vap-create-") as tmp:
    directory = Path(tmp)
    c = directory / "vap-create.c"
    c.write_text(code)
    binary = directory / "vap-create"
    command = [a.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror"]
    command += ["-static"] if a.qemu else ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    command += [str(c), "-o", str(binary)]
    subprocess.run(command, check=True)
    subprocess.run([str(a.qemu), str(binary)] if a.qemu else [str(binary)], check=True)
