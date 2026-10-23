#!/usr/bin/env python3
"""Execute the actual BSS confirmation handler with a removed VAP.

The descriptor lists, DMA unmap, cfg80211 and firmware submission are fixtures;
this does not emulate concurrent tasklets or the radio.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree", type=Path)
parser.add_argument("--before", action="store_true", help="expect the old reset behavior")
parser.add_argument("--before-metadata", action="store_true",
                    help="expect the old reserve-frame metadata mixup")
parser.add_argument("--cc", default="cc")
parser.add_argument("--qemu", type=Path)
args = parser.parse_args()
source = (args.tree / "wireless/driver/shared/hw_mmb.c").read_text()
match = re.search(r"^int _mtlk_mmb_handle_bss_cfm\([^;]*?\)\s*\{", source, re.M)
assert match
end, depth = match.end(), 1
while depth:
    depth += (source[end] == "{") - (source[end] == "}")
    end += 1
handler = source[match.start():end]

fixture = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint32_t uint32;
typedef int BOOL;
typedef struct entry { struct entry *next; } mtlk_dlist_entry_t;
typedef struct { mtlk_dlist_entry_t *first,*last; } mtlk_dlist_t;
typedef struct { uint8 au8Addr[6]; } mac_t;
typedef mac_t IEEE_ADDR;
typedef struct { mac_t dst_addr; } frame_head_t;
struct sk_buff { unsigned id; };
struct wireless_dev { int live; };
struct net_device { int live; };
struct ieee80211_hw { int live; };
typedef struct { unsigned id; } wave_radio_t;
typedef struct { unsigned id; } mtlk_df_t;
typedef struct { unsigned id; } mtlk_df_user_t;
typedef struct { unsigned id; } core_t;
typedef core_t *mtlk_vap_handle_t;
typedef struct mtlk_hw_bss_req_mirror {
  struct { mtlk_dlist_entry_t list_entry; } hdr;
  uint8 *virt_addr;
  uint32 size,dma_addr,vap_id,radio_id,extra_processing,action_code,subtype;
  uint32 power_mgmt_on,tid;
  uint64_t cookie;
  mac_t dst_addr;
  int is_broadcast,dma_mapped;
  struct sk_buff *skb;
} request_t;
typedef struct { unsigned nof_bds; request_t req[2]; } basic_t;
typedef struct { basic_t basic; mtlk_dlist_t used_list,free_list; unsigned lock; } bdr_t;
struct mtlk_bss_management { bdr_t tx_bdr,tx_res_bdr; unsigned tx_ring_last_cfm_ts; };
typedef struct { struct mtlk_bss_management bss_mgmt; int mac_events_stopped; void *radio_descr; } mtlk_hw_t;
typedef struct { uint32 u32frameInfo0,u32frameInfo1,index; } HOST_DSC;
#define MTLK_ERR_OK 0
#define MTLK_ERR_UNKNOWN -1
#define MTLK_HW_RESET 1
#define NET_STATE_CONNECTED 1
#define NET_STATE_DEACTIVATING 2
#define PROCESS_MANAGEMENT 3
#define PROCESS_NULL_DATA_PACKET 4
#define GFP_ATOMIC 0
#define FALSE 0
#define __UNLIKELY(x) (x)
#define READ_ONCE(x) (x)
#define MTLK_ASSERT(x) assert(x)
#define LE32_TO_CPU(x) (x)
#define HD_BD_INDEX_GET(x) ((x)->index)
#define MTLK_BFIELD_GET(x,f) (x)
#define _mtlk_basic_bdr_get_mirror_bd(b,i,t) (&(b)->req[i])
#define MTLK_LIST_GET_CONTAINING_RECORD(p,t,field) ((t *)((char *)(p)-offsetof(t,field)))
#define ILOG3_D(...) ((void)0)
#define ILOG2_DD(...) ((void)0)
#define ILOG3_DDHPDD(...) ((void)0)
#define ILOG3_P(...) ((void)0)
#define ILOG3_PD(...) ((void)0)
#define ILOG3_DDHPD(...) ((void)0)
#define ELOG_DD(...) ((void)0)
#define WLOG_DD(...) ((void)0)
static unsigned resets,unmaps,drops,ap_status,probe_status,core_cfms,res_freed,submissions;
static unsigned confirmed_peer,confirmed_extra,confirmed_subtype,confirmed_broadcast;
static int main_vap_present,reserve_vap_present;
static core_t core={1};
static wave_radio_t radio={1};
static struct net_device netdev={1};
static struct wireless_dev wdev={1};
static struct ieee80211_hw ieee={1};
static mtlk_df_t df={1};
static mtlk_df_user_t user={1};
static void list_push(mtlk_dlist_t *l,mtlk_dlist_entry_t *e) {
  e->next=NULL;if(l->last) l->last->next=e;else l->first=e;l->last=e;
}
static mtlk_dlist_entry_t *mtlk_dlist_pop_front(mtlk_dlist_t *l) {
  mtlk_dlist_entry_t *e=l->first;if(e) {l->first=e->next;if(!l->first)l->last=NULL;e->next=NULL;}return e;
}
static void mtlk_dlist_push_back(mtlk_dlist_t *l,mtlk_dlist_entry_t *e) {list_push(l,e);}
static void mtlk_dlist_remove(mtlk_dlist_t *l,mtlk_dlist_entry_t *e) {
  mtlk_dlist_entry_t *prev=NULL,*cur=l->first;
  while(cur && cur!=e){prev=cur;cur=cur->next;}assert(cur);
  if(prev)prev->next=e->next;else l->first=e->next;
  if(l->last==e)l->last=prev;e->next=NULL;
}
static unsigned mtlk_dlist_size(mtlk_dlist_t *l) {
  unsigned n=0;for(mtlk_dlist_entry_t *e=l->first;e;e=e->next)n++;return n;
}
static void mtlk_osal_atomic_set(unsigned *p,unsigned v) {*p=v;}
static unsigned mtlk_osal_timestamp(void) {return 123;}
static void __wave_hw_rx_hd_decode(mtlk_hw_t *h,unsigned ep,unsigned v,uint8 *r,uint8 *id) {
  (void)h;(void)ep;(void)v;*r=0;*id=0;
}
static wave_radio_t *__mtlk_hw_wave_radio_get(mtlk_hw_t *h,unsigned id) {(void)h;assert(!id);return &radio;}
static int _mtlk_mmb_get_vap_is_not_ready(mtlk_hw_t *h,unsigned r,unsigned id) {(void)h;(void)r;(void)id;return 0;}
static mtlk_vap_handle_t _mtlk_mmb_get_vap_handle_from_vap_id(mtlk_hw_t *h,unsigned r,unsigned id) {
  (void)h;(void)r;return (id?reserve_vap_present:main_vap_present)?&core:NULL;
}
static void wave_bss_tx_unmap(mtlk_hw_t *h,request_t *r) {
  (void)h;assert(r->dma_mapped);r->dma_mapped=0;r->dma_addr=0;unmaps++;
}
static mtlk_df_t *mtlk_vap_get_df(core_t *v) {assert(v);return &df;}
static mtlk_df_user_t *mtlk_df_get_user(mtlk_df_t *d) {assert(d);return &user;}
static struct net_device *mtlk_df_user_get_ndev(mtlk_df_user_t *u) {assert(u);return &netdev;}
static struct wireless_dev *mtlk_df_user_get_wdev(mtlk_df_user_t *u) {assert(u);return &wdev;}
static int mtlk_vap_is_ap(core_t *v) {assert(v);return 1;}
static void cfg80211_mgmt_tx_status(struct wireless_dev *w,uint64_t c,void *p,unsigned n,int s,unsigned f) {
  (void)c;(void)p;(void)n;(void)s;(void)f;assert(w->live);ap_status++;
}
static void cfg80211_probe_status(struct net_device *n,uint8 *a,uint64_t c,int s,int rate,int ack,unsigned f) {
  (void)a;(void)c;(void)s;(void)rate;(void)ack;(void)f;assert(n->live);probe_status++;
}
static struct ieee80211_hw *wave_radio_ieee80211_hw_get(wave_radio_t *r) {assert(r);return &ieee;}
static void wv_ieee80211_tx_status(struct ieee80211_hw *h,struct sk_buff *s,unsigned v) {
  (void)v;assert(h->live);free(s);drops++;
}
static void dev_kfree_skb_any(struct sk_buff *s) {assert(s);free(s);drops++;}
static void mtlk_osal_lock_acquire(unsigned *p) {assert(p);}
static void mtlk_osal_lock_release(unsigned *p) {assert(p);}
static void wave_bss_queued_tx_failed(mtlk_hw_t *h,request_t *r,core_t *v) {
  (void)h;(void)v;if(r->skb){dev_kfree_skb_any(r->skb);r->skb=NULL;}
}
static core_t *mtlk_vap_get_core(core_t *v) {assert(v);return v;}
static void mtlk_core_on_bss_res_freed(core_t *v) {assert(v);res_freed++;}
static int mtlk_core_get_net_state(core_t *v) {assert(v);return NET_STATE_CONNECTED;}
static int _mtlk_mmb_bss_mgmt_tx(mtlk_hw_t *h,request_t *r,core_t *v) {
  (void)h;assert(r && v);submissions++;return MTLK_ERR_OK;
}
static void mtlk_core_on_bss_cfm(core_t *v,mac_t *a,unsigned x,unsigned y,int z) {
  assert(v);core_cfms++;confirmed_peer=a->au8Addr[0];confirmed_extra=x;
  confirmed_subtype=y;confirmed_broadcast=z;
}
static void *wave_radio_descr_hw_api_get(void *d,unsigned r) {(void)d;(void)r;return &radio;}
static void mtlk_hw_set_prop(void *api,unsigned prop,void *d,unsigned n) {
  (void)api;(void)d;(void)n;assert(prop==MTLK_HW_RESET);resets++;
}
HANDLER
static request_t *prepare(mtlk_hw_t *hw,int reserve) {
  request_t *r;memset(hw,0,sizeof(*hw));
  hw->bss_mgmt.tx_bdr.basic.nof_bds=1;
  r=&hw->bss_mgmt.tx_bdr.basic.req[0];
  r->virt_addr=calloc(1,64);assert(r->virt_addr);r->size=64;r->dma_mapped=1;r->dma_addr=0x1000;
  r->extra_processing=PROCESS_MANAGEMENT;r->cookie=42;r->skb=calloc(1,sizeof(*r->skb));assert(r->skb);
  r->dst_addr.au8Addr[0]=0x11;r->subtype=11;r->is_broadcast=1;
  list_push(&hw->bss_mgmt.tx_bdr.used_list,&r->hdr.list_entry);
  if(reserve) {
    request_t *s=&hw->bss_mgmt.tx_res_bdr.basic.req[0];
    s->virt_addr=calloc(1,64);assert(s->virt_addr);s->size=64;s->vap_id=1;
    s->skb=calloc(1,sizeof(*s->skb));assert(s->skb);
    s->dst_addr.au8Addr[0]=0x22;s->extra_processing=PROCESS_NULL_DATA_PACKET;
    s->subtype=22;s->is_broadcast=0;
    list_push(&hw->bss_mgmt.tx_res_bdr.used_list,&s->hdr.list_entry);
  }
  return r;
}
static void reset_counts(void) {
  resets=unmaps=drops=ap_status=probe_status=core_cfms=res_freed=submissions=0;
  confirmed_peer=confirmed_extra=confirmed_subtype=confirmed_broadcast=0;
  main_vap_present=reserve_vap_present=0;
}
static void dispose(mtlk_hw_t *hw) {
  for(int q=0;q<2;q++) for(int i=0;i<2;i++) {
    request_t *r=q?&hw->bss_mgmt.tx_res_bdr.basic.req[i]:&hw->bss_mgmt.tx_bdr.basic.req[i];
    free(r->skb);free(r->virt_addr);
  }
}
int main(void) {
  mtlk_hw_t hw;HOST_DSC hd={0};request_t *r;
  reset_counts();r=prepare(&hw,0);
  int ret=_mtlk_mmb_handle_bss_cfm(&hw,&hd);
#ifdef BEFORE
  assert(ret==MTLK_ERR_UNKNOWN && resets==1 && unmaps==0 && drops==0 && r->dma_mapped);
  dispose(&hw);return 0;
#elif defined(BEFORE_META)
  dispose(&hw);reset_counts();r=prepare(&hw,1);
  main_vap_present=reserve_vap_present=1;
  ret=_mtlk_mmb_handle_bss_cfm(&hw,&hd);
  assert(ret==MTLK_ERR_OK && core_cfms==1 && confirmed_peer==0x22 && !r->dma_mapped);
  assert(confirmed_extra==PROCESS_NULL_DATA_PACKET && confirmed_subtype==22 && !confirmed_broadcast);
  dispose(&hw);return 0;
#else
  assert(ret==MTLK_ERR_OK && !resets && unmaps==1 && drops==1);
  assert(!r->dma_mapped && !r->skb && !mtlk_dlist_size(&hw.bss_mgmt.tx_bdr.used_list));
  assert(mtlk_dlist_size(&hw.bss_mgmt.tx_bdr.free_list)==1 && !ap_status && !core_cfms);
  dispose(&hw);
  reset_counts();r=prepare(&hw,1);ret=_mtlk_mmb_handle_bss_cfm(&hw,&hd);
  assert(ret==MTLK_ERR_OK && !resets && unmaps==1 && drops==2 && !submissions);
  assert(!mtlk_dlist_size(&hw.bss_mgmt.tx_res_bdr.used_list));
  assert(!mtlk_dlist_size(&hw.bss_mgmt.tx_bdr.used_list) && !core_cfms);
  dispose(&hw);
  reset_counts();r=prepare(&hw,1);reserve_vap_present=1;
  ret=_mtlk_mmb_handle_bss_cfm(&hw,&hd);
  assert(ret==MTLK_ERR_OK && !resets && unmaps==1 && drops==1 && submissions==1);
  assert(!core_cfms && res_freed==1 && mtlk_dlist_size(&hw.bss_mgmt.tx_bdr.used_list)==1);
  dispose(&hw);
  reset_counts();r=prepare(&hw,1);main_vap_present=reserve_vap_present=1;
  ret=_mtlk_mmb_handle_bss_cfm(&hw,&hd);
  assert(ret==MTLK_ERR_OK && core_cfms==1 && submissions==1 && !resets);
  assert(confirmed_peer==0x11 && confirmed_extra==PROCESS_MANAGEMENT);
  assert(confirmed_subtype==11 && confirmed_broadcast==1);
  dispose(&hw);
  reset_counts();r=prepare(&hw,0);main_vap_present=1;
  ret=_mtlk_mmb_handle_bss_cfm(&hw,&hd);
  assert(ret==MTLK_ERR_OK && !resets && unmaps==1 && drops==1 && ap_status==1 && core_cfms==1);
  dispose(&hw);
  reset_counts();r=prepare(&hw,0);hw.mac_events_stopped=1;
  ret=_mtlk_mmb_handle_bss_cfm(&hw,&hd);
  assert(ret==MTLK_ERR_OK && !resets && !unmaps && !drops && r->dma_mapped);
  dispose(&hw);
  reset_counts();r=prepare(&hw,0);hd.index=1;
  ret=_mtlk_mmb_handle_bss_cfm(&hw,&hd);
  assert(ret==MTLK_ERR_UNKNOWN && resets==1 && !unmaps);
  dispose(&hw);
  return 0;
#endif
}
'''
with tempfile.TemporaryDirectory(prefix="ax3000-bss-removed-") as directory:
    directory = Path(directory)
    c = directory / "test.c"
    binary = directory / "test"
    c.write_text(fixture.replace("HANDLER", handler))
    command = [args.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror",
               "-Wno-unused-function", "-Wno-misleading-indentation",
               "-O1", "-g", *(["-DBEFORE"] if args.before else
                             ["-DBEFORE_META"] if args.before_metadata else []),
               str(c), "-o", str(binary)]
    if not args.qemu:
        command[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    else:
        command[1:1] = ["-static"]
    subprocess.run(command, check=True)
    subprocess.run(([str(args.qemu)] if args.qemu else []) + [str(binary)], check=True)
print("PASS: actual BSS handler", "before reset reproduced" if args.before else
      "before metadata mixup reproduced" if args.before_metadata else
      "removed VAP reclaimed, original metadata retained, reserves and controls pass")
