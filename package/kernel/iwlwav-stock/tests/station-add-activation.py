#!/usr/bin/env python3
"""Fault-inject the actual station add, activation, MAC and errno callbacks."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


p = argparse.ArgumentParser(description=__doc__)
p.add_argument("tree", type=Path)
p.add_argument("--cc", default="cc")
p.add_argument("--qemu", type=Path)
a = p.parse_args()


def extract(path, name):
    source = (a.tree / path).read_text()
    match = re.search(r"^(?:static )?int\s+(?:__MTLK_IFUNC\s+)?" + re.escape(name) +
                      r"\s*\([^;]*?\)\s*\{", source, re.M | re.S)
    if not match:
        raise ValueError(name)
    end = source.find("\n}", match.end())
    if end < 0:
        raise ValueError(f"unterminated {name}")
    return source[match.start() : end + 2]


mac = "wireless/driver/linux/mac80211.c"
add = extract(mac, "_wv_ieee80211_op_add_interface")
activate = extract(mac, "wv_activate_vif")
set_mac = extract(mac, "wv_set_mac_addr_pdb")
translate = extract("wireless/driver/linux/mtlk_df_user.c", "_mtlk_df_mtlk_to_linux_error_code")
errors = (a.tree / "wireless/shared/mtlkerr.h").read_text()
definitions = re.findall(r"MTLK_NAMED_ENUM_ENTRY\((MTLK_ERR_\w+),\s*\((-?\d+)\)", errors)
if len(definitions) < 30:
    raise ValueError("unexpected WAVE error enum")
defines = "\n".join(f"#define {name} {number}" for name, number in definitions)

code = r'''
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

ERROR_DEFINES
#define __MTLK_IFUNC
#define TRUE 1
#define FALSE 0
#define ETH_ALEN 6
#define ENOTSUPP EOPNOTSUPP
#define NL80211_IFTYPE_STATION 2
#define MTLK_ROLE_STA 2
#define IFF_DONT_BRIDGE 0x800
#define MAX_VAP_WAIT_RETRIES 600
#define WAVE_RADIO_REQ_MBSS_ADD_VAP_NAME 1
#define WAVE_CORE_REQ_SET_MAC_ADDR 2
#define WAVE_CORE_REQ_ACTIVATE_OPEN 3
#define WAVE_RADIO_REQ_MBSS_DEL_VAP_NAME 4
#define MTLK_ASSERT(x) assert(x)
#define ASSERT(x) assert(x)
#define WAVE_WV_CHECK_PTR_RES(x) do { if (!(x)) return -EINVAL; } while (0)
#define MTLK_CLPB_TRY(value, size) do { if ((value) != NULL) {
#define MTLK_CLPB_FINALLY(result) } } while (0); if (1)
#define MTLK_CLPB_END
#define ILOG1_SSD(...) ((void)0)
#define ILOG0_SY(...) ((void)0)
#define ILOG0_SD(...) ((void)0)
#define ILOG2_V(...) ((void)0)
#define ELOG_V(...) ((void)0)
#define ELOG_S(...) ((void)0)
#define ELOG_D(...) ((void)0)
typedef uint32_t uint32;
typedef struct { int id; } mtlk_core_t;
typedef struct { mtlk_core_t *core; int id; } mtlk_vap_info_internal_t;
typedef mtlk_vap_info_internal_t *mtlk_vap_handle_t;
typedef struct { mtlk_vap_handle_t vap; } mtlk_df_t;
struct net_device_ops { int (*ndo_start_xmit)(void); int marker; };
struct net_device { const struct net_device_ops *netdev_ops; unsigned int priv_flags; int refs; };
typedef struct { mtlk_df_t *df; struct net_device *ndev; struct net_device_ops ops; } mtlk_df_user_t;
typedef struct { int id; } mtlk_clpb_t;
typedef struct {
  const char *added_vap_name;
  void *wiphy;
  int role, is_master;
  struct net_device *ndev;
  mtlk_vap_handle_t vap_handle;
} mtlk_mbss_cfg_t;
struct wv_vif_priv {
  mtlk_df_user_t *df_user;
  unsigned int vap_index;
  unsigned long latest_rx_and_tx_packets;
  int ndp_counter;
  const struct net_device_ops *mac80211_netdev_ops;
  struct ieee80211_vif *vif;
};
struct ieee80211_vif {
  struct wv_vif_priv *drv_priv;
  int type;
  char addr[ETH_ALEN];
};
struct mutex { int held; };
typedef struct {
  struct ieee80211_vif **vif_array;
  mtlk_df_t *master_df;
  struct mutex vif_mutex;
} wv_mac80211_t;
struct ieee80211_hw { wv_mac80211_t *priv; void *wiphy; };
struct mtlk_ap_settings {
  int beacon_interval, dtim_period, hidden_ssid, essid_len;
  char essid[33];
};
static struct { char comm[16]; int pid; } task __attribute__((unused)) = {"test", 1};
#define current (&task)
static int init_net;
static int activation_result, mac_result, delete_result, live_vap, delete_calls, pending_delete;
static struct net_device_ops original_ops = {0, 1};
static struct net_device ndev;
static mtlk_core_t master_core, child_core;
static mtlk_vap_info_internal_t master_vap = {.core=&master_core}, child_vap = {.core=&child_core};
static mtlk_df_t master_df = {&master_vap}, child_df = {&child_vap};
static mtlk_df_user_t child_user;
static mtlk_df_user_t *child_user_ptr = &child_user;
static struct wv_vif_priv priv;
static struct ieee80211_vif vif, *vif_array[2];
static wv_mac80211_t mac80211;
static struct ieee80211_hw hw;
static mtlk_clpb_t clpb;

static void mutex_lock(struct mutex *value) { assert(!value->held); value->held = 1; }
static void mutex_unlock(struct mutex *value) { assert(value->held); value->held = 0; }
static int wave_sta_vap_delete_pending(wv_mac80211_t *value) {
  (void)value; return pending_delete;
}
static const char *ieee80211_vif_to_name(struct ieee80211_vif *v) { (void)v; return "wlan0"; }
static wv_mac80211_t *__wv_ieee80211_hw_get_mac80211(struct ieee80211_hw *h) { return h->priv; }
static mtlk_df_t *_wv_mac80211_master_df_get(wv_mac80211_t *m) { return m->master_df; }
static mtlk_vap_handle_t mtlk_df_get_vap_handle(mtlk_df_t *d) { return d->vap; }
static mtlk_core_t *mtlk_vap_get_core(mtlk_vap_handle_t v) { return v->core; }
static int wait_rcvry_completion_if_needed(mtlk_core_t *c) { (void)c; return MTLK_ERR_OK; }
static struct net_device *dev_get_by_name(int *net, const char *name) {
  (void)net; (void)name; ++ndev.refs; return &ndev;
}
static void dev_put(struct net_device *d) { assert(d == &ndev); --d->refs; }
static __attribute__((unused)) mtlk_df_user_t *mtlk_df_get_user(mtlk_df_t *d) { (void)d; return &child_user; }
static __attribute__((unused)) const char *mtlk_df_user_get_name(mtlk_df_user_t *u) { (void)u; return "wlan0"; }
static mtlk_df_t *mtlk_df_user_get_df(mtlk_df_user_t *u) { return u->df; }
static struct net_device_ops *mtlk_df_user_get_ndev_ops(mtlk_df_user_t *u) { return &u->ops; }
static int _mtlk_df_user_linux_start_tx(void) { return 0; }
static void mtlk_osal_msleep(int ms) { (void)ms; }
static int _mtlk_df_user_invoke_core(mtlk_df_t *d, int request, mtlk_clpb_t **out,
                                     const void *payload, size_t size) {
  (void)d; (void)payload; (void)size; *out = &clpb;
  if (request == WAVE_RADIO_REQ_MBSS_ADD_VAP_NAME) { live_vap = 1; return MTLK_ERR_OK; }
  if (request == WAVE_CORE_REQ_SET_MAC_ADDR) return mac_result;
  if (request == WAVE_CORE_REQ_ACTIVATE_OPEN) return activation_result;
  if (request == WAVE_RADIO_REQ_MBSS_DEL_VAP_NAME) {
    ++delete_calls;
    if (delete_result == MTLK_ERR_OK) live_vap = 0;
    return delete_result;
  }
  assert(0); return MTLK_ERR_UNKNOWN;
}
static int _mtlk_df_user_process_core_retval_void(int result, mtlk_clpb_t *c,
                                                   int request, int value) {
  (void)c; (void)request; (void)value; return result;
}
static int _mtlk_df_user_process_core_retval(int result, mtlk_clpb_t *c,
                                              int request, int value) {
  (void)c; (void)request; (void)value; return result;
}
static void *mtlk_clpb_enum_get_next(mtlk_clpb_t *c, uint32 *size) {
  (void)c; if (size) *size = sizeof(child_user_ptr); return &child_user_ptr;
}
static void mtlk_clpb_delete(mtlk_clpb_t *c) { (void)c; }

ACTUAL_TRANSLATE
ACTUAL_ACTIVATE
ACTUAL_SET_MAC
ACTUAL_ADD

static void reset(int activation, int mac, int deletion) {
  activation_result = activation; mac_result = mac;
  delete_result = deletion; live_vap = delete_calls = pending_delete = 0;
  memset(&priv, 0, sizeof(priv)); memset(&child_user, 0, sizeof(child_user));
  ndev.netdev_ops = &original_ops; ndev.priv_flags = IFF_DONT_BRIDGE; ndev.refs = 1;
  child_user.df = &child_df; child_user.ndev = &ndev;
  child_vap.id = 1;
  vif.type = NL80211_IFTYPE_STATION; vif.drv_priv = &priv;
  vif_array[0] = NULL; vif_array[1] = NULL;
  mac80211.vif_array = vif_array; mac80211.master_df = &master_df;
  hw.priv = &mac80211; hw.wiphy = &hw;
}
static int run(const char *name, int activation, int mac, int deletion,
               int expected, int expected_live) {
  int result, safe, failed;
  reset(activation, mac, deletion);
  result = _wv_ieee80211_op_add_interface(&hw, &vif);
  /* A nonzero add result means mac80211 will never call remove_interface. */
  safe = result == 0 || !live_vap;
  failed = result != expected || !safe || live_vap != expected_live || ndev.refs != 1;
  if (activation || mac) {
    failed += delete_calls == 0;
    if (deletion == MTLK_ERR_OK)
      failed += vif_array[1] != NULL || ndev.netdev_ops != &original_ops || priv.df_user != NULL;
    else
      failed += vif_array[1] != &vif || ndev.netdev_ops != &child_user.ops ||
                priv.df_user != &child_user;
  }
  printf("%s: %s, result=%d live_vap=%d vif_published=%d netdev_refs=%d delete_calls=%d\n",
         failed ? "FAIL" : "PASS", name, result, live_vap,
         vif_array[1] == &vif, ndev.refs, delete_calls);
  return failed;
}
int main(void) {
  int failed = 0, result;
  reset(MTLK_ERR_OK, MTLK_ERR_OK, MTLK_ERR_OK);
  pending_delete = 1;
  result = _wv_ieee80211_op_add_interface(&hw, &vif);
  failed += result != -EBUSY || live_vap || ndev.refs != 1;
  printf("%s: pending-delete-admission, result=%d live_vap=%d\n",
         result == -EBUSY && !live_vap ? "PASS" : "FAIL", result, live_vap);
  failed += run("ordinary-add", MTLK_ERR_OK, MTLK_ERR_OK, MTLK_ERR_OK, 0, 1);
  failed += run("activation-no-memory", MTLK_ERR_NO_MEM, MTLK_ERR_OK,
                MTLK_ERR_OK, -ENOMEM, 0);
  failed += run("MAC-write-failure", MTLK_ERR_OK, MTLK_ERR_HW,
                MTLK_ERR_OK, -EFAULT, 0);
  failed += run("activation-rollback-retry", MTLK_ERR_NO_MEM, MTLK_ERR_OK,
                MTLK_ERR_RETRY, 0, 1);
  return failed ? 1 : 0;
}
'''.replace("ERROR_DEFINES", defines).replace("ACTUAL_TRANSLATE", translate).replace(
    "ACTUAL_ACTIVATE", activate).replace("ACTUAL_SET_MAC", set_mac).replace("ACTUAL_ADD", add)

with tempfile.TemporaryDirectory(prefix="ax3000-add-activation-") as tmp:
    c = Path(tmp) / "add-activation.c"
    binary = Path(tmp) / "add-activation"
    c.write_text(code)
    command = [a.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror"]
    command += ["-static"] if a.qemu else ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    command += [str(c), "-o", str(binary)]
    subprocess.run(command, check=True)
    command = [str(a.qemu), str(binary)] if a.qemu else [str(binary)]
    raise SystemExit(subprocess.run(command, check=False).returncode)
