#!/usr/bin/env python3
"""Exercise the actual reserved-BSS failure helper across AP teardown."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree", type=Path)
parser.add_argument("--before", type=Path)
parser.add_argument("--cc", default="gcc")
parser.add_argument("--qemu", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()


def extract(path):
    source = path.read_text()
    match = re.search(r"^static void\s+wave_bss_queued_tx_failed\s*\([^;]*?\)\s*\{", source, re.M)
    assert match
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


current = next(args.tree.glob("wireless/driver/shared/hw_mmb.c"))
function = extract(current)
assert "!READ_ONCE(hw->mac_events_stopped)" in function

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define READ_ONCE(x) (x)
#define PROCESS_MANAGEMENT 1
#define GFP_ATOMIC 0
#define FALSE 0
struct sk_buff { int marker; };
struct wireless_dev { int live; };
struct ieee80211_hw { int live; };
typedef struct { struct wireless_dev wdev; } mtlk_df_user_t;
typedef struct { mtlk_df_user_t user; } mtlk_df_t;
typedef struct { int is_ap; mtlk_df_t df; } mtlk_vap_t;
typedef mtlk_vap_t *mtlk_vap_handle_t;
typedef struct { int mac_events_stopped; } mtlk_hw_t;
typedef struct { struct ieee80211_hw hw; } wave_radio_t;
struct mtlk_hw_bss_req_mirror { uint64_t cookie; void *virt_addr;
  unsigned size, radio_id, extra_processing; struct sk_buff *skb; };
static wave_radio_t radio;
static unsigned callbacks, station_statuses, raw_drops, skbs;
static int mtlk_vap_is_ap(mtlk_vap_handle_t v){return v->is_ap;}
static mtlk_df_t *mtlk_vap_get_df(mtlk_vap_handle_t v){return &v->df;}
static mtlk_df_user_t *mtlk_df_get_user(mtlk_df_t *df){return &df->user;}
static struct wireless_dev *mtlk_df_user_get_wdev(mtlk_df_user_t *u){return &u->wdev;}
static void cfg80211_mgmt_tx_status(struct wireless_dev *w,uint64_t cookie,
  void *data,unsigned size,bool ack,int flags){(void)ack;(void)flags;
  assert(w->live && cookie && data && size);callbacks++;}
static wave_radio_t *__mtlk_hw_wave_radio_get(mtlk_hw_t *hw,unsigned id){
  (void)hw;assert(id<2);return &radio;}
static struct ieee80211_hw *wave_radio_ieee80211_hw_get(wave_radio_t *r){return &r->hw;}
static void wv_ieee80211_tx_status(struct ieee80211_hw *h,struct sk_buff *s,int status){
  (void)status;assert(h->live && s && skbs);station_statuses++;skbs--;free(s);}
static void dev_kfree_skb_any(struct sk_buff *s){assert(s && skbs);raw_drops++;skbs--;free(s);}
FUNCTION
static void run_case(int stopped,int ap,int cookie,int with_vap){
  mtlk_hw_t hw={.mac_events_stopped=stopped};
  mtlk_vap_t vap={.is_ap=ap,.df.user.wdev.live=!stopped};
  unsigned char payload[16]={1};
  struct mtlk_hw_bss_req_mirror req={.cookie=cookie,.virt_addr=payload,
    .size=sizeof(payload),.radio_id=0,.extra_processing=PROCESS_MANAGEMENT};
  callbacks=station_statuses=raw_drops=0;skbs=1;radio.hw.live=1;
  req.skb=calloc(1,sizeof(*req.skb));assert(req.skb);
  wave_bss_queued_tx_failed(&hw,&req,with_vap?&vap:NULL);
  assert(!skbs && !req.skb);
  assert(callbacks==(!stopped && ap && cookie && with_vap));
  assert(station_statuses==(!ap && with_vap));
  assert(raw_drops==(ap || !with_vap));
}
int main(void){unsigned cases=0;
  for(int stopped=0;stopped<2;stopped++)for(int ap=0;ap<2;ap++)
    for(int cookie=0;cookie<2;cookie++)for(int vap=0;vap<2;vap++){
      run_case(stopped,ap,cookie,vap);cases++;}
  assert(cases==16);puts("PASS: 16 AP/STA, gate, cookie and VAP cases; every skb consumed");
  return 0;
}
'''


def run(output, source_function, should_pass):
    output.mkdir(parents=True, exist_ok=True)
    (output / "probe.c").write_text(harness.replace("\nFUNCTION\n", "\n" + source_function + "\n"))
    flags = ["-static"] if args.qemu else ["-fsanitize=address,undefined", "-fno-pie", "-no-pie"]
    subprocess.run([args.cc, "-std=gnu11", "-O1", "-g", *flags,
                    str(output / "probe.c"), "-o", str(output / "probe")], check=True)
    command = [str(output / "probe")]
    if args.qemu:
        command.insert(0, str(args.qemu.resolve()))
    result = subprocess.run(command, cwd=output, capture_output=True, text=True)
    if should_pass:
        assert result.returncode == 0, result.stderr
        print(result.stdout.strip())
    else:
        assert result.returncode != 0, "old source unexpectedly passed the closed-wdev case"
        print("PASS: old source rejected by closed-wdev negative control")


if args.output:
    run(args.output.resolve(), function, True)
    if args.before:
        run(args.output.resolve() / "before", extract(args.before), False)
else:
    with tempfile.TemporaryDirectory(prefix="wave-ap-status-") as temporary:
        run(Path(temporary), function, True)
        if args.before:
            run(Path(temporary) / "before", extract(args.before), False)
