#!/usr/bin/env python3
"""Model a hardware tasklet resuming after terminal station removal."""

import argparse
from pathlib import Path
import subprocess
import tempfile


p = argparse.ArgumentParser(description=__doc__)
p.add_argument("tree", type=Path)
p.add_argument("--cc", default="cc")
a = p.parse_args()
source = (a.tree / "wireless/driver/linux/mac80211.c").read_text()
header_source = (a.tree / "wireless/driver/linux/mac80211.h").read_text()
tasklet_source = (a.tree / "wireless/driver/shared/hw_mmb.c").read_text()
if "wave_vap_increment_ndp_counter" not in source:
    if ("wave_vap_increment_ndp_counter" in header_source or
            "wave_vap_increment_ndp_counter" in tasklet_source or
            "ndp_counter" in source or "_wave_vap_get_vif_priv" in source):
        raise ValueError("unused NDP tasklet reader only partly removed")
    print("PASS: no tasklet VIF reader for unused NDP counter")
    raise SystemExit(0)
if "wave_vap_increment_ndp_counter(vap_handle);" not in tasklet_source:
    raise ValueError("NDP counter call site changed")


def extract(name):
    match = source.find("\n" + name + " (")
    if match < 0:
        match = source.find("\n" + name + "(")
    if match < 0:
        raise ValueError(name)
    start = source.rfind("\n\n", 0, match) + 2
    end = source.find("\n}", match)
    if end < 0:
        raise ValueError(f"unterminated {name}")
    return source[start : end + 2]


functions = "\n\n".join(extract(name) for name in (
    "_wv_mac80211_get_vif", "_wv_mac80211_get_vif_priv",
    "_wave_vap_get_vif_priv", "wave_vap_increment_ndp_counter"))
needle = "  if (NULL != wv_iface_inf)\n    wv_iface_inf->ndp_counter++;"
if functions.count(needle) != 1:
    raise ValueError("NDP counter read point changed")

template = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define __MTLK_IFUNC
#define MTLK_ASSERT(x) assert(x)
typedef uint8_t u8;
struct wv_vif_priv { int ndp_counter; };
struct ieee80211_vif { struct wv_vif_priv *drv_priv; };
struct _wv_mac80211_t { struct ieee80211_vif **vif_array; };
typedef struct _wv_mac80211_t wv_mac80211_t;
struct vap_handle { int id; };
typedef struct vap_handle *mtlk_vap_handle_t;
static struct _wv_mac80211_t radio_mac;
static struct ieee80211_vif *old_vif;
static struct wv_vif_priv *old_priv;
static int released;

static struct _wv_mac80211_t *_wave_vap_get_mac80211(mtlk_vap_handle_t handle) {
  (void)handle; return &radio_mac;
}
static int mtlk_vap_get_id(mtlk_vap_handle_t handle) { return handle->id; }
static void interleave_drop_vif(void) {
  /* remove_interface has returned; mac80211 discards its driver-private
   * VIF state and may release the netdev/VIF allocation. */
#ifndef LEAVE_STALE_SLOT
  radio_mac.vif_array[1] = NULL;
#endif
  released = 1;
  free(old_priv);
  free(old_vif);
}

ACTUAL_FUNCTIONS

int main(void) {
  struct ieee80211_vif *slots[2] = {0};
  struct vap_handle handle = {1};
  old_vif = malloc(sizeof(*old_vif));
  old_priv = malloc(sizeof(*old_priv));
  assert(old_vif && old_priv);
  old_priv->ndp_counter = 0;
  old_vif->drv_priv = old_priv;
  slots[1] = old_vif;
  radio_mac.vif_array = slots;
#ifdef RELEASE_BEFORE_READ
  interleave_drop_vif();
#endif
  wave_vap_increment_ndp_counter(&handle);
  if (!released) {
    assert(old_priv->ndp_counter == 1);
    interleave_drop_vif();
  }
  return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="ax3000-vif-reader-") as directory:
    directory = Path(directory)
    failures = 0
    for scenario in ("control", "fetched_then_delete", "timeout_stale_slot"):
        func = functions.replace(needle, ("  interleave_drop_vif();\n"
                                         if scenario == "fetched_then_delete" else "") + needle)
        c = directory / (scenario + ".c")
        binary = directory / c.stem
        c.write_text(template.replace("ACTUAL_FUNCTIONS", func))
        command = [a.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                   str(c), "-o", str(binary)]
        if scenario == "timeout_stale_slot":
            command[1:1] = ["-DLEAVE_STALE_SLOT", "-DRELEASE_BEFORE_READ"]
        subprocess.run(command, check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if scenario == "control":
            if result.returncode:
                print(result.stderr)
                raise SystemExit(2)
            print("PASS: ordinary tasklet NDP count")
        elif result.returncode and "heap-use-after-free" in result.stderr:
            print(f"FAIL: {scenario} tasklet read after VIF release (ASan heap-use-after-free)")
            failures += 1
        else:
            print(result.stderr)
            raise SystemExit(2 if result.returncode else 0)
    raise SystemExit(1 if failures else 0)
