#!/usr/bin/env python3
"""Check that unconnected-station requests cannot outlive their cfg80211 owner."""

import argparse
from pathlib import Path
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree", type=Path)
parser.add_argument("--cc", default="cc")
args = parser.parse_args()

wave_source = (args.tree / "wireless/driver/linux/wave_radio.c").read_text()
core_source = (args.tree / "wireless/driver/linux/core.c").read_text()


def extract_function(source, name):
    start_name = -1
    for marker in (name + "(", name + " ("):
        search_from = 0
        while True:
            candidate = source.find(marker, search_from)
            if candidate < 0:
                break
            brace = source.find("{", candidate)
            semicolon = source.find(";", candidate)
            if brace >= 0 and (semicolon < 0 or brace < semicolon):
                start_name = candidate
                break
            search_from = candidate + len(marker)
        if start_name >= 0:
            break
    if start_name < 0:
        raise ValueError(f"{name} definition missing")
    start = source.rfind("\n", 0, start_name) + 1
    brace = source.find("{", start_name)
    if brace < 0:
        raise ValueError(f"{name} body missing")
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise ValueError(f"{name} unterminated")


submit = extract_function(wave_source, "wave_radio_unconnected_sta_get")
handler = extract_function(core_source, "_mtlk_core_get_unconnected_station")

if "_mtlk_df_user_invoke_core_async" in submit:
    raise ValueError("unconnected-station request still queues a raw wdev asynchronously")
for needle in (
    "mtlk_clpb_t *clpb = NULL;",
    "res = _mtlk_df_user_invoke_core(master_df,",
    "WAVE_CORE_REQ_GET_UNCONNECTED_STATION, &clpb,",
    "res = _mtlk_df_user_process_core_retval_void(res, clpb,",
):
    if needle not in submit:
        raise ValueError(f"synchronous request lifetime guard missing: {needle}")

invoke_pos = submit.index("res = _mtlk_df_user_invoke_core(master_df,")
process_pos = submit.index("res = _mtlk_df_user_process_core_retval_void")
return_pos = submit.index("return _mtlk_df_mtlk_to_linux_error_code(res);")
if not invoke_pos < process_pos < return_pos:
    raise ValueError("synchronous request/result ordering is wrong")

init_pos = handler.index("memset(&sta_res_data, 0, sizeof(sta_res_data));")
addr_pos = handler.index("sta_res_data.addr = sta_req_data->addr;")
lookup_pos = handler.index("df_user = mtlk_df_user_from_wdev(sta_req_data->wdev);")
if not init_pos < addr_pos < lookup_pos:
    raise ValueError("response is not initialized before the first stale-interface exit")
if handler.count("memset(&sta_res_data, 0, sizeof(sta_res_data));") != 1:
    raise ValueError("response initialization must have one unambiguous owner")

code = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define MTLK_ERR_OK 0
#define MTLK_ERR_NOT_SUPPORTED (-17)
#define MTLK_ERR_PARAMS (-22)
#define TRUE 1
#define WAVE_CORE_REQ_GET_UNCONNECTED_STATION 77
#define MTLK_ASSERT(x) assert(x)
#define ILOG1_SSD(fmt, a, b, c) do { (void)(a); (void)(b); (void)(c); } while (0)
#define ILOG2_DY(fmt, a, b) do { (void)(a); (void)(b); } while (0)
#define ELOG_V(...) ((void)0)
#define ELOG_D(...) ((void)0)
#define ELOG_Y(...) ((void)0)

typedef struct { uint8_t au8Addr[6]; } IEEE_ADDR;
typedef struct { int value; } mtlk_clpb_t;
typedef struct { int value; } mtlk_df_t;
struct test_vap { int value; };
typedef struct test_vap *mtlk_vap_handle_t;
struct test_hw_api { void *hw; };
typedef struct { struct test_hw_api *hw_api; mtlk_df_t *master_df; } wave_radio_t;
struct net_device { char name[16]; };
struct wireless_dev { struct net_device *netdev; };
struct task_struct { char comm[16]; int pid; } test_current = {"tester", 42};
#define current (&test_current)

struct vendor_unconnected_sta_req_data {
  uint32_t chan_width, center_freq, cf1, cf2;
  IEEE_ADDR addr;
};
struct vendor_unconnected_sta_req_data_internal {
  uint32_t chan_width, center_freq, cf1, cf2;
  IEEE_ADDR addr;
  struct wireless_dev *wdev;
};

static int gen6, invoke_result, invokes, processes, wdev_live;
static mtlk_clpb_t clipboard;
static struct test_vap vap;

static int mtlk_hw_type_is_gen6(void *hw) { (void)hw; return gen6; }
static int mtlk_osal_eth_is_broadcast(const uint8_t *addr) {
  int i; for (i = 0; i < 6; ++i) if (addr[i] != 0xff) return 0; return 1;
}
static int ieee_addr_is_valid(const IEEE_ADDR *addr) {
  int i, nonzero = 0; for (i = 0; i < 6; ++i) nonzero |= addr->au8Addr[i];
  return nonzero && !(addr->au8Addr[0] & 1);
}
static mtlk_df_t *wave_radio_df_get(wave_radio_t *radio) { return radio->master_df; }
static mtlk_vap_handle_t mtlk_df_get_vap_handle(mtlk_df_t *df) {
  (void)df; return &vap;
}
static int mtlk_vap_get_oid(mtlk_vap_handle_t handle) { return handle->value; }
static int _mtlk_df_user_invoke_core(mtlk_df_t *df, int request,
    mtlk_clpb_t **clpb, const void *data, size_t size) {
  const struct vendor_unconnected_sta_req_data_internal *req = data;
  (void)df;
  assert(request == WAVE_CORE_REQ_GET_UNCONNECTED_STATION);
  assert(size == sizeof(*req));
  assert(wdev_live && req->wdev && req->wdev->netdev);
  ++invokes;
  *clpb = &clipboard;
  return invoke_result;
}
static int _mtlk_df_user_process_core_retval_void(int result, mtlk_clpb_t *clpb,
    int request, int delete_on_success) {
  assert(wdev_live);
  assert(clpb == &clipboard);
  assert(request == WAVE_CORE_REQ_GET_UNCONNECTED_STATION && delete_on_success);
  ++processes;
  return result;
}
static int _mtlk_df_mtlk_to_linux_error_code(int result) { return result; }

ACTUAL_FUNCTION

static void reset(void) {
  gen6 = 0; invoke_result = 0; invokes = 0; processes = 0; wdev_live = 1;
}

int main(void) {
  struct test_hw_api api = {0};
  mtlk_df_t master = {0};
  wave_radio_t radio = {&api, &master};
  struct net_device ndev = {"wlan0"};
  struct wireless_dev wdev = {&ndev};
  struct vendor_unconnected_sta_req_data req = {
    .chan_width = 1, .center_freq = 5180, .cf1 = 5210, .cf2 = 0,
    .addr = {{0x02, 0, 0, 0, 0, 1}},
  };

  reset();
  assert(wave_radio_unconnected_sta_get(&radio, &wdev, &req, sizeof(req)) == 0);
  assert(invokes == 1 && processes == 1 && wdev_live);
  wdev_live = 0; /* callback lifetime may end only after the function returns */

  reset(); invoke_result = -19;
  assert(wave_radio_unconnected_sta_get(&radio, &wdev, &req, sizeof(req)) == -19);
  assert(invokes == 1 && processes == 1);

  reset(); gen6 = 1;
  assert(wave_radio_unconnected_sta_get(&radio, &wdev, &req, sizeof(req)) ==
         MTLK_ERR_NOT_SUPPORTED);
  assert(!invokes && !processes);

  reset();
  assert(wave_radio_unconnected_sta_get(&radio, &wdev, &req, sizeof(req) - 1) ==
         MTLK_ERR_PARAMS);
  assert(!invokes && !processes);

  reset();
  assert(wave_radio_unconnected_sta_get(&radio, &wdev, NULL, sizeof(req)) ==
         MTLK_ERR_PARAMS);
  assert(!invokes && !processes);

  reset(); memset(req.addr.au8Addr, 0xff, sizeof(req.addr.au8Addr));
  assert(wave_radio_unconnected_sta_get(&radio, &wdev, &req, sizeof(req)) ==
         MTLK_ERR_PARAMS);
  assert(!invokes && !processes);

  puts("PASS: synchronous unconnected-station request retains callback lifetime");
  return 0;
}
'''.replace("ACTUAL_FUNCTION", submit)

with tempfile.TemporaryDirectory(prefix="ax3000-unconnected-sta-") as directory:
    source_file = Path(directory) / "unconnected-sta.c"
    binary = Path(directory) / "unconnected-sta"
    source_file.write_text(code)
    command = [
        args.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        str(source_file), "-o", str(binary),
    ]
    subprocess.run(command, check=True)
    raise SystemExit(subprocess.run([str(binary)], check=False).returncode)
