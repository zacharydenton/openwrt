#!/usr/bin/env python3
"""Fault-inject the prepared WAVE station start and MBSS add callbacks."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree", type=Path)
parser.add_argument("--cc", default="cc")
parser.add_argument("--qemu", type=Path)
args = parser.parse_args()


def extract(path, name):
    source = (args.tree / path).read_text()
    match = re.search(r"^static int\s+" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", source, re.M | re.S)
    if not match:
        raise ValueError(f"missing {name}")
    end = source.find("\n}", match.end())
    if end < 0:
        raise ValueError(f"unterminated {name}")
    return source[match.start() : end + 2]


start = extract("wireless/driver/linux/mac80211.c", "_wv_ieee80211_op_start")
add = extract("wireless/driver/linux/core.c", "_mtlk_core_add_vap_name")
code = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MTLK_ERR_OK 0
#define MTLK_ERR_NO_MEM (-6)
#define MTLK_ERR_NO_RESOURCES (-28)
#define MTLK_ERR_RETRY (-11)
#define LINUX_ERR_OK 0
#define ENOMEM 12
#define TRUE 1
#define MTLK_MEM_TAG_MAC80211 0
#define MTLK_ROLE_AP 1
#define MTLK_ROLE_STA 2
#define MTLK_ASSERT(x) assert(x)
#define WAVE_WV_CHECK_PTR_RES(x) do { if (!(x)) return -22; } while (0)
#define HANDLE_T_PTR(type, handle) ((type *)(handle))
#define MTLK_CLPB_TRY(value, size) if ((value) != NULL)
#define MTLK_CLPB_FINALLY(result) if (1)
#define MTLK_CLPB_END
#define MTLK_CLPB_EXIT(error) return (error)
#define ILOG0_V(...) ((void)0)
#define ELOG_V(...) ((void)0)
#define ELOG_D(...) ((void)0)
typedef unsigned int uint32;
typedef void *mtlk_handle_t;
struct vap { int id; };
typedef struct vap *mtlk_vap_handle_t;
typedef struct { mtlk_vap_handle_t vap_handle; } mtlk_core_t;
typedef struct { int id; } mtlk_df_t;
typedef struct { int id; } mtlk_df_user_t;
typedef struct { int id; } mtlk_clpb_t;
typedef struct {
  int role, is_master;
  const char *added_vap_name;
  void *wiphy, *ndev;
} mtlk_mbss_cfg_t;
struct mutex { int held; };
typedef struct {
  void *radio;
  void *vif_array;
  struct mutex vif_mutex;
} wv_mac80211_t;
struct ieee80211_hw { wv_mac80211_t *priv; };

static int fail_alloc, fail_push, sta_exists, live_vap, stopped, deleted, purged;
static struct vap vap;
static mtlk_df_t master_df, child_df;
static mtlk_df_user_t child_user;
static wv_mac80211_t mac80211;
static struct ieee80211_hw hw;
static mtlk_core_t core;
static mtlk_mbss_cfg_t cfg;
static mtlk_clpb_t clpb;

static void mutex_lock(struct mutex *value) { assert(!value->held); value->held = 1; }
static void mutex_unlock(struct mutex *value) { assert(value->held); value->held = 0; }
static wv_mac80211_t *__wv_ieee80211_hw_get_mac80211(struct ieee80211_hw *h) { return h->priv; }
static mtlk_df_t *_wv_mac80211_master_df_get(wv_mac80211_t *m) { (void)m; return &master_df; }
static int __wv_mac80211_max_vaps_count_get(wv_mac80211_t *m) { (void)m; return 2; }
static void *mtlk_osal_mem_alloc(size_t n, int tag) { (void)tag; return fail_alloc ? NULL : malloc(n); }
static void wave_radio_set_sta_vifs_exist(void *r, int value) { (void)r; sta_exists = value; }
static void *mtlk_clpb_enum_get_next(mtlk_clpb_t *c, uint32 *n) { (void)c; (void)n; return &cfg; }
static int mtlk_core_is_block_tx_mode(mtlk_core_t *c) { (void)c; return 0; }
static int mtlk_core_is_in_scan_mode(mtlk_core_t *c) { (void)c; return 0; }
static void *mtlk_vap_get_manager(mtlk_vap_handle_t v) { (void)v; return &vap; }
static int mtlk_vap_manager_get_free_vap_index(void *m, uint32 *index) {
  (void)m; *index = 1; return 0;
}
static int mtlk_vap_manager_create_vap(void *m, uint32 index, void *wiphy,
                                       const char *name, int role, int master, void *ndev) {
  (void)m; (void)index; (void)wiphy; (void)name; (void)role; (void)master; (void)ndev;
  live_vap = 1; return 0;
}
static int mtlk_vap_manager_get_vap_handle(void *m, uint32 index, mtlk_vap_handle_t *out) {
  (void)m; (void)index; *out = &vap; return 0;
}
static mtlk_df_t *mtlk_vap_get_df(mtlk_vap_handle_t v) { (void)v; return &child_df; }
static mtlk_df_user_t *mtlk_df_get_user(mtlk_df_t *d) { (void)d; return &child_user; }
static void *mtlk_df_user_get_wdev(mtlk_df_user_t *u) { return u; }
static int mtlk_clpb_push(mtlk_clpb_t *c, const void *p, size_t n) {
  (void)c; (void)p; (void)n; return fail_push ? MTLK_ERR_NO_MEM : MTLK_ERR_OK;
}
static void mtlk_clpb_purge(mtlk_clpb_t *c) { (void)c; ++purged; }
static void __attribute__((unused)) mtlk_vap_stop(mtlk_vap_handle_t v) { assert(v == &vap); ++stopped; }
static void __attribute__((unused)) mtlk_vap_delete(mtlk_vap_handle_t v) { assert(v == &vap); ++deleted; live_vap = 0; }

ACTUAL_START
ACTUAL_ADD

static int test_start(void) {
  int failed = 0, result;
  memset(&mac80211, 0, sizeof(mac80211)); hw.priv = &mac80211;
  fail_alloc = 1; sta_exists = 0;
  result = _wv_ieee80211_op_start(&hw);
  failed += result != -ENOMEM || sta_exists;
  printf("%s: start-allocation-failure, result=%d sta_exists=%d\n",
         failed ? "FAIL" : "PASS", result, sta_exists);
  fail_alloc = 0; sta_exists = 0;
  result = _wv_ieee80211_op_start(&hw);
  failed += result != 0 || !sta_exists || !mac80211.vif_array;
  printf("%s: ordinary-start, result=%d sta_exists=%d\n",
         result || !sta_exists || !mac80211.vif_array ? "FAIL" : "PASS", result, sta_exists);
  free(mac80211.vif_array);
  return failed;
}
static int test_add(int role, int push_failure) {
  mtlk_clpb_t *ptr = &clpb;
  int result, failed;
  cfg.role = role; cfg.added_vap_name = "wlan0"; cfg.is_master = 0;
  core.vap_handle = &vap;
  fail_push = push_failure; live_vap = stopped = deleted = purged = 0;
  result = _mtlk_core_add_vap_name(&core, &ptr, sizeof(ptr));
  failed = push_failure
    ? result != MTLK_ERR_NO_MEM || live_vap || stopped != 1 || deleted != 1 || purged != 1
    : result != 0 || !live_vap || stopped || deleted || purged;
  printf("%s: %s-%s, result=%d live_vap=%d stopped=%d deleted=%d purged=%d\n",
         failed ? "FAIL" : "PASS", role == MTLK_ROLE_AP ? "AP" : "STA",
         push_failure ? "push-failure" : "ordinary-add", result,
         live_vap, stopped, deleted, purged);
  return failed;
}
int main(void) {
  int failed = test_start();
  failed += test_add(MTLK_ROLE_AP, 1);
  failed += test_add(MTLK_ROLE_STA, 1);
  failed += test_add(MTLK_ROLE_AP, 0);
  failed += test_add(MTLK_ROLE_STA, 0);
  return failed ? 1 : 0;
}
'''.replace("ACTUAL_START", start).replace("ACTUAL_ADD", add)

with tempfile.TemporaryDirectory(prefix="ax3000-station-rollback-") as directory:
    source_file = Path(directory) / "station-rollback.c"
    binary = Path(directory) / "station-rollback"
    source_file.write_text(code)
    command = [args.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror"]
    command += ["-static"] if args.qemu else ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    command += [str(source_file), "-o", str(binary)]
    subprocess.run(command, check=True)
    command = [str(args.qemu), str(binary)] if args.qemu else [str(binary)]
    raise SystemExit(subprocess.run(command, check=False).returncode)
