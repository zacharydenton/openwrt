#!/usr/bin/env python3
"""Fault-inject deferred station VAP removal and its independent ownership."""

import argparse
from pathlib import Path
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree", type=Path)
parser.add_argument("--cc", default="cc")
args = parser.parse_args()
source = (args.tree / "wireless/driver/linux/mac80211.c").read_text()
df_source = (args.tree / "wireless/driver/linux/mtlk_df_user.c").read_text()


def extract(name):
    for spelling in (name + " (", name + "("):
        match = source.find(spelling)
        if match >= 0:
            break
    else:
        raise ValueError(f"{name} missing")
    start = source.rfind("\n\n", 0, match) + 2
    end = source.find("\n}", match)
    if end < 0:
        raise ValueError(f"{name} unterminated")
    return source[start : end + 2]


functions = "\n\n".join(extract(name) for name in (
    "wave_sta_vap_delete_one",
    "wave_sta_vap_delete_pending",
    "wave_sta_vap_delete_work",
    "wave_sta_vap_delete_defer",
    "wave_sta_vap_delete_stop",
    "_wv_ieee80211_op_remove_interface",
))
for needle in ("mutex_lock(&mac80211->vif_mutex)",
               "mac80211->vif_array[wv_iface_inf->vap_index] = NULL",
               "wave_sta_vap_delete_defer(mac80211, _vap_to_be_removed)"):
    if needle not in functions:
        raise ValueError(f"station removal lifetime guard missing: {needle}")
for needle in ("if (wave_sta_vap_delete_pending(mac80211))\n    return -EBUSY;",
               "wave_sta_vap_delete_stop(mac80211);",
               "mtlk_osal_mem_free(mac80211->pending_vap_delete)"):
    if needle not in source:
        raise ValueError(f"station removal lifecycle guard missing: {needle}")
for needle in ("dev_hold(ndev);", "dev_put(ndev);"):
    if needle not in df_source:
        raise ValueError(f"station netdev ownership missing: {needle}")

code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define MTLK_ERR_OK 0
#define MTLK_ERR_RETRY (-11)
#define MTLK_ERR_NOT_READY (-19)
#define FALSE 0
#define TRUE 1
#define WAVE_RADIO_REQ_MBSS_DEL_VAP_NAME 1
#define MAX_VAP_WAIT_RETRIES 600
#define MTLK_ASSERT(x) assert(x)
#define ASSERT(x) assert(x)
#define WAVE_WV_CHECK_PTR_VOID(x) do { if (!(x)) return; } while (0)
#define ILOG0_SY(...) ((void)0)
#define ILOG0_SD(...) ((void)0)
#define ELOG_V(...) ((void)0)
#define ELOG_D(...) ((void)0)
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define to_delayed_work(work) container_of(work, struct delayed_work, work)
typedef uint32_t uint32;
typedef struct { int id; } mtlk_core_t;
struct vap_handle { mtlk_core_t *core; unsigned int id; };
typedef struct vap_handle *mtlk_vap_handle_t;
typedef struct { mtlk_vap_handle_t vap; } mtlk_df_t;
struct net_device_ops { int id; };
struct net_device { struct net_device_ops *netdev_ops; int refs; };
typedef struct { mtlk_df_t *df; struct net_device *ndev; } mtlk_df_user_t;
typedef struct { int result; } mtlk_clpb_t;
typedef struct { mtlk_vap_handle_t vap_handle; } mtlk_mbss_cfg_t;
struct mutex { int held; };
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; int scheduled; };
struct wv_vif_priv {
  struct ieee80211_vif *vif;
  mtlk_df_user_t *df_user;
  unsigned int vap_index;
  int vif_sid, is_set_sid, is_initialized;
  unsigned long latest_rx_and_tx_packets;
  struct net_device_ops *mac80211_netdev_ops;
};
struct ieee80211_vif { struct wv_vif_priv *drv_priv; };
typedef struct {
  mtlk_df_t *master_df;
  struct ieee80211_vif **vif_array;
  struct mutex vif_mutex, vap_delete_mutex;
  struct delayed_work vap_delete_work;
  mtlk_vap_handle_t *pending_vap_delete;
  bool vap_delete_stopping;
} wv_mac80211_t;
struct ieee80211_hw { wv_mac80211_t *priv; };

static int wait_result, delete_result, live_vap, sleeps, cancels;
static struct net_device_ops original_ops = {1}, driver_ops = {2};
static struct net_device ndev;
static mtlk_core_t core;
static struct vap_handle vap;
static mtlk_df_t df, master_df;
static mtlk_df_user_t user;
static struct wv_vif_priv vif_priv;
static struct ieee80211_vif vif, *vif_array[2];
static mtlk_vap_handle_t pending[2];
static wv_mac80211_t mac80211;
static struct ieee80211_hw hw;

static void mutex_lock(struct mutex *value) { assert(!value->held); value->held = 1; }
static void mutex_unlock(struct mutex *value) { assert(value->held); value->held = 0; }
static unsigned long msecs_to_jiffies(unsigned long value) { return value; }
static bool schedule_delayed_work(struct delayed_work *work, unsigned long delay) {
  assert(delay == 1000); work->scheduled = 1; return true;
}
static void cancel_delayed_work_sync(struct delayed_work *work) {
  work->scheduled = 0; ++cancels;
}
static int __wv_mac80211_max_vaps_count_get(wv_mac80211_t *value) {
  (void)value; return 2;
}
static wv_mac80211_t *__wv_ieee80211_hw_get_mac80211(struct ieee80211_hw *value) {
  return value->priv;
}
static mtlk_df_t *_wv_mac80211_master_df_get(wv_mac80211_t *value) {
  return value->master_df;
}
static mtlk_df_t *mtlk_df_user_get_df(mtlk_df_user_t *value) { return value->df; }
static struct net_device *mtlk_df_user_get_ndev(mtlk_df_user_t *value) { return value->ndev; }
static mtlk_vap_handle_t mtlk_df_get_vap_handle(mtlk_df_t *value) { return value->vap; }
static mtlk_core_t *mtlk_vap_get_core(mtlk_vap_handle_t value) { return value->core; }
static unsigned int mtlk_vap_get_id(mtlk_vap_handle_t value) { return value->id; }
static int wait_rcvry_completion_if_needed(mtlk_core_t *value) {
  (void)value; return wait_result;
}
static int wv_release_sid(mtlk_df_user_t *value, int sid) {
  (void)value; (void)sid; return MTLK_ERR_OK;
}
static int _mtlk_df_user_invoke_core(mtlk_df_t *master, int request,
                                     mtlk_clpb_t **clpb, mtlk_mbss_cfg_t *cfg,
                                     size_t size) {
  (void)master; (void)request; (void)clpb; (void)cfg; (void)size;
  if (delete_result == MTLK_ERR_OK) {
    assert(live_vap && ndev.refs > 0);
    live_vap = 0;
    --ndev.refs; /* station DF releases its independently held netdev ref */
  }
  return delete_result;
}
static int _mtlk_df_user_process_core_retval(int result, mtlk_clpb_t *clpb,
                                              int request, int value) {
  (void)clpb; (void)request; (void)value; return result;
}
static void mtlk_osal_msleep(int ms) { assert(ms == 50); ++sleeps; }

ACTUAL_FUNCTIONS

static void reset(int wait, int remove) {
  memset(&mac80211, 0, sizeof(mac80211));
  memset(pending, 0, sizeof(pending));
  wait_result = wait; delete_result = remove; live_vap = 1; sleeps = 0;
  ndev.netdev_ops = &driver_ops;
  ndev.refs = 2; /* one mac80211 owner plus the VAP/DF owner */
  vap.core = &core; vap.id = 1; df.vap = &vap; master_df.vap = &vap;
  user.df = &df; user.ndev = &ndev;
  vif_priv.vif = &vif; vif_priv.df_user = &user;
  vif_priv.mac80211_netdev_ops = &original_ops;
  vif_priv.vap_index = 1; vif_priv.is_set_sid = 0;
  vif.drv_priv = &vif_priv;
  vif_array[0] = NULL; vif_array[1] = &vif;
  mac80211.master_df = &master_df; mac80211.vif_array = vif_array;
  mac80211.pending_vap_delete = pending;
  hw.priv = &mac80211;
}

static void mac80211_release_netdev(void) {
  assert(ndev.refs > 0); --ndev.refs;
}

static int run_case(const char *name, int wait, int remove, bool deferred,
                    bool master_present) {
  reset(wait, remove);
  if (!master_present)
    mac80211.master_df = NULL;
  _wv_ieee80211_op_remove_interface(&hw, &vif);
  assert(vif_array[1] == NULL);
  assert(vif_priv.vif == NULL && vif_priv.df_user == NULL);
  assert(ndev.netdev_ops == &original_ops);
  assert(live_vap == deferred);
  assert(wave_sta_vap_delete_pending(&mac80211) == deferred);
  assert(mac80211.vap_delete_work.scheduled == deferred);

  mac80211_release_netdev();
  if (deferred) {
    assert(ndev.refs == 1); /* orphan VAP keeps the unregistered netdev alive */
    mac80211.master_df = &master_df;
    wait_result = MTLK_ERR_OK;
    delete_result = MTLK_ERR_OK;
    mac80211.vap_delete_work.scheduled = 0; /* execute the queued worker */
    wave_sta_vap_delete_work(&mac80211.vap_delete_work.work);
    assert(!live_vap && !pending[1] && ndev.refs == 0);
  } else {
    assert(ndev.refs == 0);
  }
  printf("PASS: %s, deferred=%d retries=%d\n", name, deferred, sleeps);
  return 0;
}

int main(void) {
  run_case("recovery-timeout", MTLK_ERR_NOT_READY, MTLK_ERR_OK, true, true);
  run_case("delete-retry-exhausted", MTLK_ERR_OK, MTLK_ERR_RETRY, true, true);
  run_case("master-unavailable", MTLK_ERR_OK, MTLK_ERR_OK, true, false);
  run_case("ordinary-delete", MTLK_ERR_OK, MTLK_ERR_OK, false, true);

  reset(MTLK_ERR_NOT_READY, MTLK_ERR_RETRY);
  wave_sta_vap_delete_defer(&mac80211, &vap);
  assert(wave_sta_vap_delete_pending(&mac80211));
  wave_sta_vap_delete_stop(&mac80211);
  assert(mac80211.vap_delete_stopping && !mac80211.vap_delete_work.scheduled);
  assert(cancels > 0 && live_vap && ndev.refs == 2);
  delete_result = MTLK_ERR_OK; /* VAP-manager teardown owns the final release */
  assert(wave_sta_vap_delete_one(&mac80211, &vap) == MTLK_ERR_OK);
  mac80211_release_netdev();
  assert(ndev.refs == 0);
  puts("PASS: worker shutdown leaves final VAP ownership to manager teardown");
  return 0;
}
'''.replace("ACTUAL_FUNCTIONS", functions)

with tempfile.TemporaryDirectory(prefix="ax3000-station-remove-") as directory:
    source_file = Path(directory) / "station-remove.c"
    binary = Path(directory) / "station-remove"
    source_file.write_text(code)
    command = [args.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
               "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
               str(source_file), "-o", str(binary)]
    subprocess.run(command, check=True)
    raise SystemExit(subprocess.run([str(binary)], check=False).returncode)
