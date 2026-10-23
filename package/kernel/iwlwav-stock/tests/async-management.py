#!/usr/bin/env python3
"""Execute async station TX/request ownership with a deferred serializer fixture.

Uses actual TX entry, async invocation/completion and core management handler.
Kernel allocation, clipboard storage, firmware/DMA and mac80211 are modeled.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('tree',type=Path)
p.add_argument('--before',type=Path)
p.add_argument('--cc',default='gcc')
p.add_argument('--qemu',type=Path)
p.add_argument('--output',type=Path)
p.add_argument('--case',choices=['all','null-callback','station-drain'],default='all')
a=p.parse_args()
root=a.before or a.tree
mac=(root/'wireless/driver/linux/mac80211.c').read_text()
df=(root/'wireless/driver/linux/mtlk_df_linux.c').read_text()
core=(root/'wireless/driver/linux/core.c').read_text()
ui=(a.tree/'wireless/driver/shared/mtlk_coreui.h').read_text()
hw=(root/'wireless/driver/shared/hw_mmb.c').read_text()
clip=(a.tree/'wireless/driver/shared/mtlk_clipboard.h').read_text()

def extract(text,name):
    m=re.search(r'^(?:static\s+)?(?:__INLINE\s+)?(?:void|int)\s+(?:__MTLK_IFUNC\s+)?'+name+r'\s*\([^;]*?\)\s*\{',text,re.M)
    assert m,name
    end,depth=m.end(),1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[m.start():end]

params=re.search(r'struct mgmt_tx_params\n\{.*?\n\};',ui,re.S).group()
async_ctx=re.search(r'typedef struct __async_invoke_ctx_t\n\{.*?\} _async_invoke_ctx_t;',df,re.S).group()
async_funcs='\n'.join(extract(df,n) for n in ['mtlk_df_ui_req_complete','_mtlk_df_ui_req_cleanup','_mtlk_df_ui_req_get_result','_core_async_invoke_clb','_mtlk_df_user_invoke_core_async'])
owner=''
if 'struct wave_sta_tx_request {' in mac:
    owner=re.search(r'struct wave_sta_tx_request \{.*?\n\};',mac,re.S).group()+'\n'+extract(mac,'wave_sta_tx_request_done')
mac_tx=extract(mac,'_wv_ieee80211_op_tx')
core_tx=extract(core,'_mtlk_core_mgmt_tx')
core_dispatch=extract(core,'_mtlk_core_async_clb')
current_mac=(a.tree/'wireless/driver/linux/mac80211.c').read_text()
lifetime_struct=re.search(r'struct wave_sta_tx_lifetime \{.*?\n\};',current_mac,re.S).group()
lifetime_helpers='\n'.join(extract(current_mac,n) for n in ['wave_sta_tx_lifetime_init','wave_sta_tx_put','wv_ieee80211_tx_quiesce'])
# Boolean-returning helpers use the same brace extraction.
for name in ['wave_sta_tx_get','wave_sta_tx_idle']:
    function=extract(current_mac.replace('static bool\n'+name,'static int\n'+name),name)
    lifetime_helpers=function.replace('static int','static bool',1)+'\n'+lifetime_helpers
unregister=extract(mac,'wv_ieee80211_unregister')
drv=(a.tree/'wireless/driver/linux/mtlk_mmb_drv.c').read_text()
cleanup=extract(drv,'_mmb_drv_cleanup')
assert cleanup.index('wave_radio_mac80211_tx_quiesce(radio_descr)') < cleanup.index('wave_rcvry_cleanup_finalize')
assert current_mac.index('wave_sta_tx_lifetime_init(mac80211);') < current_mac.index('mac80211->radio = radio;')
macros=clip[clip.index('#define MTLK_CLPB_TRY'):clip.index('void __MTLK_IFUNC\nmtlk_clpb_enum_rewind')]
drop=hw[hw.index('frame_drop:',hw.index('_mtlk_mmb_bss_mgmt_tx_submit (')):hw.index('\nint\nmtlk_mmb_bss_mgmt_tx (')]
drop=drop.replace('frame_drop:','')

h=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
#define __MTLK_IFUNC
#define __INLINE inline
#define MTLK_ASSERT(x) assert(x)
#define MTLK_UNREFERENCED_PARAM(x) ((void)(x))
#define HANDLE_T(p) ((uintptr_t)(p))
#define HANDLE_T_PTR(t,h) ((t *)(h))
#define GFP_ATOMIC 0
#define FALSE 0
#define TRUE 1
#define unlikely(x) (x)
#define ELOG_V(...) ((void)0)
#define ELOG_D(...) ((void)0)
#define ELOG_Y(...) ((void)0)
#define WLOG_V(...) ((void)0)
#define WLOG_DD(...) ((void)0)
#define WLOG_DDDD(...) ((void)0)
#define ILOG0_V(...) ((void)0)
#define ILOG1_DSDDS(...) ((void)0)
#define ILOG2_DDY(...) ((void)0)
#define ILOG2_DY(...) ((void)0)
#define MTLK_ERR_OK 0
#define MTLK_ERR_UNKNOWN -1
#define MTLK_ERR_NO_MEM -2
#define MTLK_ERR_PARAMS -3
#define MTLK_ERR_NOT_HANDLED -4
#define MTLK_ERR_CLPB_DATA -5
#define MTLK_ERR_NOT_READY -6
#define MTLK_ERR_CANCELED -7
#define MTLK_ERR_BUSY -8
#define MTLK_MEM_TAG_CORE_INVOKE 0
#define WAVE_CORE_REQ_MGMT_TX 7
#define WAVE_RADIO_REQ_MBSS_ADD_VAP_IDX 100
#define WAVE_RADIO_REQ_MBSS_ADD_VAP_NAME 101
#define WAVE_RADIO_REQ_MBSS_DEL_VAP_IDX 102
#define WAVE_RADIO_REQ_MBSS_DEL_VAP_NAME 103
#define PROCESS_MANAGEMENT 0
#define PROCESS_NULL_DATA_PACKET 1
#define PROCESS_EAPOL 2
#define ETH_HLEN 14
#define NTS_TID_USE_DEFAULT 0
#define DB_UNKNOWN_SID 65535
#define MTLK_PCKT_FLTR_DISCARD_ALL 1
#define MTLK_TX_DISCARDED_DROP_ALL_FILTER 1
#define MAN_TYPE_PROBE_RES 5
#define FRAME_SUBTYPE_MASK 0xf0
#define FRAME_SUBTYPE_SHIFT 4
#define IEEE80211_TX_CTL_NO_ACK 1
#define IEEE80211_TX_CTL_NO_CCK_RATE 2
typedef uint8_t u8;typedef uint8_t uint8;typedef uint16_t uint16;typedef uint32_t uint32;typedef uint64_t uint64;typedef uint64_t u64;
typedef uintptr_t mtlk_handle_t;typedef unsigned mtlk_core_tx_req_id_t;
typedef unsigned mtlk_slid_t;
typedef int (*mtlk_df_ui_caller_func_t)(mtlk_handle_t,const void *,uint32);
struct ieee80211_hdr { uint16 frame_control; };
struct ieee80211_channel { int center_freq; };
struct cfg80211_chan_def { struct ieee80211_channel *chan; };
struct ieee80211_conf { struct cfg80211_chan_def chandef; };
struct wv_vif_priv { void *df_user; };
struct ieee80211_vif { struct wv_vif_priv drv_priv[1]; };
struct ieee80211_tx_info { struct { struct ieee80211_vif *vif; } control; unsigned flags; };
struct sk_buff { struct ieee80211_tx_info info; void *dev; size_t len; uint8 data[32]; };
struct ieee80211_hw { struct ieee80211_conf conf;void *priv; };
struct ieee80211_tx_control { int unused; };
typedef struct sk_buff mtlk_nbuf_t;
typedef struct { void *vap_handle; } mtlk_df_t;
typedef mtlk_df_t mtlk_df_user_t;
struct wireless_dev { int unused; };
struct ethhdr { uint8 h_dest[6]; };
typedef struct { uint8 addr[6]; } IEEE_ADDR;
typedef struct { int unused; } sta_entry;
typedef struct { void *vap_handle; struct { int stadb; } *slow_ctx; } mtlk_core_t;
PARAMS
typedef struct { struct mgmt_tx_params params; unsigned size; int result; } mtlk_clpb_t;
typedef void (*_invoke_async_clb_t)(mtlk_handle_t,int,mtlk_clpb_t *);
typedef struct {
    int result,is_waitable,caller_pending,caller_result;
    mtlk_df_ui_caller_func_t caller_func;
    mtlk_handle_t caller_object;
    const void *caller_data;
    uint32 caller_data_size;
    int caller_done_event;
    union { int completion_event; struct { void (*clb)(mtlk_handle_t);mtlk_handle_t ctx; } notification_clb; } u;
} mtlk_user_request_t;
static unsigned fail_at,alloc_step,live_allocs,live_skbs,drops,statuses,submitted,notify_calls;
static unsigned submit_error,early_kind,finish_early,push_error,immediate,cancelled,ability_disabled;
static mtlk_user_request_t *queued_req;
static mtlk_clpb_t *queued_clip;
static struct sk_buff *firmware_skb;
static mtlk_core_t core_obj;
static unsigned stage(void) { return ++alloc_step==fail_at; }
static void *allocate(size_t n) { if(stage())return NULL;void *p=calloc(1,n);assert(p);live_allocs++;return p; }
static void kfree(void *p) { if(p){assert(live_allocs);live_allocs--;free(p);} }
#define kzalloc(n,f) allocate(n)
#define mtlk_osal_mem_alloc(n,t) allocate(n)
#define mtlk_osal_mem_free(p) kfree(p)
static void consume(struct sk_buff *skb) { assert(skb && live_skbs);live_skbs--;free(skb); }
static void ieee80211_free_txskb(struct ieee80211_hw *hw,struct sk_buff *skb) { assert(hw);drops++;consume(skb); }
static void dev_kfree_skb_any(struct sk_buff *skb) { drops++;consume(skb); }
static void wv_ieee80211_tx_status(struct ieee80211_hw *hw,struct sk_buff *skb,unsigned status) { assert(hw && !status);statuses++;consume(skb); }
static struct ieee80211_hw mac_hw;
static struct ieee80211_hw *wave_radio_ieee80211_hw_get(void *p) { assert(p);return &mac_hw; }
static int netif_running(void *dev) { return dev!=NULL; }
static int ieee80211_frequency_to_channel(int f) { assert(f==5180);return 36; }
#define IEEE80211_SKB_CB(s) (&(s)->info)
#define ieee80211_is_assoc_resp(f) ((f)==0x10)
#define ieee80211_is_reassoc_resp(f) ((f)==0x30)
#define ieee80211_is_probe_resp(f) ((f)==0x50)
#define ieee80211_is_beacon(f) ((f)==0x80)
#define ieee80211_is_nullfunc(f) ((f)==0x48)
#define ieee80211_is_qos_nullfunc(f) ((f)==0xc8)
static mtlk_df_t *mtlk_df_user_get_df(mtlk_df_user_t *user) { return user; }
static mtlk_df_t *mtlk_vap_get_df(void *v) { return v; }
static mtlk_df_user_t *mtlk_df_get_user(mtlk_df_t *df) { return df; }
static struct wireless_dev wdev;
static struct wireless_dev *mtlk_df_user_get_wdev(mtlk_df_user_t *u) { assert(u);return &wdev; }
static unsigned ap_mode;
static int mtlk_vap_is_ap(void *v) { assert(v);return ap_mode; }
static void cfg80211_mgmt_tx_status(struct wireless_dev *w,uint64 cookie,const void *buf,size_t len,int ack,int gfp) { assert(w && buf && len && !ack);(void)cookie;(void)gfp;notify_calls++; }
static mtlk_clpb_t *mtlk_clpb_create(void) { return allocate(sizeof(mtlk_clpb_t)); }
static void mtlk_clpb_delete(mtlk_clpb_t *p) { kfree(p); }
static int mtlk_clpb_push(mtlk_clpb_t *p,const void *data,size_t n) { if(stage())return -2;assert(n==sizeof(p->params));memcpy(&p->params,data,n);p->size=n;return 0; }
static void *mtlk_clpb_enum_get_next(mtlk_clpb_t *p,uint32 *size) { *size=p->size;return &p->params; }
static int mtlk_clpb_check_data(void *p,size_t got,size_t want,const char *fn,int line) { (void)fn;(void)line;return p && got==want; }
static int mtlk_clpb_push_res(mtlk_clpb_t *p,int res) { p->result=res;return push_error?-2:0; }
static int _mtlk_df_ui_notifying_req_init(mtlk_user_request_t *r,void (*clb)(mtlk_handle_t),mtlk_handle_t ctx) { if(stage())return -2;r->is_waitable=0;r->result=0;r->u.notification_clb.clb=clb;r->u.notification_clb.ctx=ctx;return 0; }
static void mtlk_osal_event_set(int *e) { (void)e;abort(); }
static void mtlk_osal_event_cleanup(int *e) { (void)e;abort(); }
static int mtlk_df_ui_req_execute_on_caller(mtlk_user_request_t *req,
    mtlk_df_ui_caller_func_t func,mtlk_handle_t object,const void *data,uint32 size) {
    (void)req;(void)func;(void)object;(void)data;(void)size;abort();
}
static void dispatch(void);
static void mtlk_core_handle_tx_ctrl(void *vap,mtlk_user_request_t *req,mtlk_core_tx_req_id_t id,mtlk_clpb_t *clip) { assert(vap && id==7 && !queued_req);queued_req=req;queued_clip=clip;if(immediate)dispatch(); }
typedef pthread_mutex_t spinlock_t;
typedef struct { pthread_mutex_t lock;pthread_cond_t cond;unsigned seq; } wait_queue_head_t;
#define spin_lock_init(p) assert(!pthread_mutex_init(p,NULL))
#define spin_lock_irqsave(p,f) do { (f)=0;assert(!pthread_mutex_lock(p)); } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(f);assert(!pthread_mutex_unlock(p)); } while(0)
#define WARN_ON_ONCE(x) (assert(!(x)),false)
static void init_waitqueue_head(wait_queue_head_t *w) {
    assert(!pthread_mutex_init(&w->lock,NULL));assert(!pthread_cond_init(&w->cond,NULL));w->seq=0;
}
static void wake_up_all(wait_queue_head_t *w) {
    assert(!pthread_mutex_lock(&w->lock));w->seq++;assert(!pthread_cond_broadcast(&w->cond));assert(!pthread_mutex_unlock(&w->lock));
}
#define wait_event(w,condition) do { for(;;) { \
    assert(!pthread_mutex_lock(&(w).lock));unsigned seq=(w).seq;assert(!pthread_mutex_unlock(&(w).lock)); \
    if(condition)break; \
    assert(!pthread_mutex_lock(&(w).lock)); \
    while(seq==(w).seq)assert(!pthread_cond_wait(&(w).cond,&(w).lock)); \
    assert(!pthread_mutex_unlock(&(w).lock)); \
} } while(0)
LIFETIME_STRUCT
typedef struct { struct wave_sta_tx_lifetime tx_lifetime;bool registered;struct ieee80211_hw *mac80211_hw; } wv_mac80211_t;
LIFETIME_HELPERS
static wv_mac80211_t mac_owner;
static atomic_uint unregister_calls;
static void ieee80211_unregister_hw(struct ieee80211_hw *hw) { assert(hw==&mac_hw && wave_sta_tx_idle(hw->priv));atomic_fetch_add(&unregister_calls,1); }
static void wave_sta_vap_delete_stop(wv_mac80211_t *mac80211) { assert(mac80211); }
UNREGISTER
static void lifetime_setup(void) {
    memset(&mac_owner,0,sizeof(mac_owner));wave_sta_tx_lifetime_init(&mac_owner);
    mac_owner.registered=true;mac_owner.mac80211_hw=&mac_hw;mac_hw.priv=&mac_owner;atomic_store(&unregister_calls,0);
}
static void lifetime_destroy(void) {
    assert(wave_sta_tx_idle(&mac_owner));
    assert(!pthread_cond_destroy(&mac_owner.tx_lifetime.wait.cond));assert(!pthread_mutex_destroy(&mac_owner.tx_lifetime.wait.lock));assert(!pthread_mutex_destroy(&mac_owner.tx_lifetime.lock));
}
ASYNC_CTX
ASYNC_FUNCS
OWNER
MAC_TX
#define WLAN_GET_ADDR1(p) ((p)+4)
static unsigned mtlk_wlan_pkt_get_frame_ctl(uint8 *p) { return p[0]; }
static sta_entry sta_obj;
static sta_entry *mtlk_stadb_find_sta(void *db,void *addr) { (void)db;(void)addr;return &sta_obj; }
static unsigned mtlk_sta_get_packets_filter(sta_entry *s) { (void)s;return 0; }
#define mtlk_sta_on_packet_dropped(...) ((void)0)
#define mtlk_sta_on_tx_packet_discarded_802_1x(...) ((void)0)
#define mtlk_sta_on_tx_packet_802_1x(...) ((void)0)
#define mtlk_sta_decref(...) ((void)0)
static uint16 mtlk_core_get_sid_by_addr(mtlk_core_t *c,char *p) { (void)c;(void)p;return early_kind==2?DB_UNKNOWN_SID:1; }
static bool _mtlk_core_ucast_probe_resp_entry_exists(mtlk_core_t *c,IEEE_ADDR *a) { (void)c;(void)a;return early_kind==3; }
#define _mtlk_core_add_ucast_probe_resp_entry(...) ((void)0)
static int wave_pmf_protect(mtlk_core_t *c,const void *b,size_t n,u8 **p,size_t *len) { (void)c;(void)b;(void)n;(void)p;(void)len;return early_kind==4?-3:0; }
static int mtlk_mmb_bss_mgmt_tx(void *vap,const uint8 *buf,size_t len,int ch,int ncck,int noack,int bc,uint64 *cookie,uint32 kind,mtlk_nbuf_t *skb,int pm,int tid) {
    assert(vap && buf && len && ch==36 && cookie && skb && !bc && !pm && !tid);(void)ncck;(void)kind;
    if(submit_error)return -6;
    *cookie=noack?0:123;submitted++;
    if(finish_early) { statuses++;consume(skb); } else { assert(!firmware_skb);firmware_skb=skb; }
    return 0;
}
CLIP_MACROS
CORE_TX
typedef struct {
    struct { bool is_cancelled;mtlk_slid_t issuer_slid; } cmd;
    void *vap_handle;unsigned ability_id;
    int (*func)(mtlk_handle_t,const void *,uint32);
    mtlk_handle_t receiver;uint32 data_size;mtlk_user_request_t *user_req;
} _core_async_exec_t;
static void *mtlk_vap_get_abmgr(void *v) { return v; }
static bool _mtlk_abmgr_is_ability_enabled(void *v,unsigned ability) { (void)ability;assert(v);return !ability_disabled; }
CORE_DISPATCH
static void dispatch(void) {
    assert(queued_req);mtlk_user_request_t *req=queued_req;mtlk_clpb_t *cp=queued_clip;queued_req=NULL;queued_clip=NULL;
    if(early_kind==1)cp->params.len=0;
    if(early_kind==2)cp->params.extra_processing=PROCESS_NULL_DATA_PACKET;
    if(early_kind==3)((uint8 *)cp->params.buf)[0]=0x50;
    if(early_kind==5)cp->size--;
    struct { _core_async_exec_t ctx;mtlk_clpb_t *data; } execution={0};
    execution.ctx.cmd.is_cancelled=cancelled;execution.ctx.vap_handle=&core_obj;
    execution.ctx.func=_mtlk_core_mgmt_tx;execution.ctx.receiver=HANDLE_T(&core_obj);
    execution.ctx.data_size=sizeof(cp);execution.ctx.user_req=req;execution.data=cp;
    assert((void *)(&execution.ctx+1)==(void *)&execution.data);
    _mtlk_core_async_clb(HANDLE_T(&execution.ctx));
}
static int drop_frame(void *vap_handle,struct sk_buff *skb,int dont_wait_for_ack) {
    void *radio=vap_handle;uint8 buf[24]={0};size_t len=sizeof(buf);uint64 local_cookie=42;
DROP_BODY
static void reset(void) {
    assert(!live_allocs && !live_skbs && !queued_req && !firmware_skb);
    assert(wave_sta_tx_idle(&mac_owner));
    fail_at=alloc_step=drops=statuses=submitted=notify_calls=0;
    submit_error=early_kind=finish_early=push_error=immediate=cancelled=ap_mode=ability_disabled=0;
}
static struct sk_buff *packet(void) { struct sk_buff *s=calloc(1,sizeof(*s));assert(s);live_skbs++;s->len=24;s->data[0]=0x40;s->dev=s;return s; }
static void send(void) {
    mtlk_df_t df={.vap_handle=&core_obj};struct ieee80211_channel ch={5180};struct ieee80211_vif vif={0};
    struct sk_buff *skb=packet();vif.drv_priv[0].df_user=&df;skb->info.control.vif=&vif;skb->info.flags=IEEE80211_TX_CTL_NO_ACK;
    mac_hw.conf.chandef.chan=&ch;core_obj.vap_handle=&df;
    _wv_ieee80211_op_tx(&mac_hw,NULL,skb);
    /* Deferred dispatch must not retain any stack-local cookie from op_tx. */
}
static void run(void) {
    send();
    if(queued_req)dispatch();
    if(firmware_skb){struct sk_buff *s=firmware_skb;firmware_skb=NULL;statuses++;consume(s);}
    assert(!live_skbs && !live_allocs && drops+statuses==1);
}
static void empty_done(mtlk_handle_t c,int res,mtlk_clpb_t *cp) { (void)c;(void)res;(void)cp;notify_calls++; }
static bool closing(void) {
    unsigned long flags;bool stopped;
    spin_lock_irqsave(&mac_owner.tx_lifetime.lock,flags);stopped=mac_owner.tx_lifetime.stopping;spin_unlock_irqrestore(&mac_owner.tx_lifetime.lock,flags);return stopped;
}
static void *remove_radio(void *arg) { wv_ieee80211_unregister(arg);return NULL; }
static void drain_scenarios(void) {
    unsigned cases=0;
    for(unsigned count=0;count<=8;count++)for(unsigned cancel=0;cancel<2;cancel++) {
        reset();lifetime_destroy();lifetime_setup();cancelled=cancel;submit_error=!cancel;
        mtlk_user_request_t *reqs[8];mtlk_clpb_t *clips[8];pthread_t remover;
        for(unsigned i=0;i<count;i++) {
            send();assert(queued_req);reqs[i]=queued_req;clips[i]=queued_clip;queued_req=NULL;queued_clip=NULL;
        }
        assert(!pthread_create(&remover,NULL,remove_radio,&mac_owner));
        while(!closing() && !atomic_load(&unregister_calls))sched_yield();
        assert(closing());if(count)assert(!atomic_load(&unregister_calls));
        unsigned old_allocs=alloc_step;send();assert(!queued_req && alloc_step==old_allocs);
        for(unsigned i=0;i<count;i++) {
            queued_req=reqs[i];queued_clip=clips[i];dispatch();
            if(i+1<count)assert(!atomic_load(&unregister_calls));
        }
        assert(!pthread_join(remover,NULL));assert(atomic_load(&unregister_calls)==1);
        assert(!mac_owner.registered && !live_allocs && !live_skbs && drops==count+1);
        wv_ieee80211_tx_quiesce(&mac_owner);wv_ieee80211_unregister(&mac_owner);
        assert(atomic_load(&unregister_calls)==1 && !wave_sta_tx_get(&mac_owner));cases++;
    }
    printf("PASS: %u concurrent unregister/deferred-request drain cases (pthread synchronization; no firmware completions)\n",cases);
}
int main(void) {
    alarm(30);unsigned cases=0;lifetime_setup();
    if(!strcmp("TEST_CASE","station-drain")) { drain_scenarios();lifetime_destroy();return 0; }
    if(!strcmp("TEST_CASE","null-callback")) {
        reset();fail_at=1;mtlk_df_t df={.vap_handle=&core_obj};struct mgmt_tx_params p={0};
        _mtlk_df_user_invoke_core_async(&df,7,&p,sizeof(p),NULL,0);
        assert(!queued_req && !live_allocs);puts("PASS: optional callback remains optional on allocation failure");lifetime_destroy();return 0;
    }
    /* First case reproduces the old stack lifetime error on deferred write. */
    reset();run();cases++;
    for(unsigned fail=1;fail<=5;fail++){reset();fail_at=fail;run();assert(!submitted);cases++;}
    for(unsigned early=0;early<=5;early++)for(unsigned sync=0;sync<2;sync++)for(unsigned finish=0;finish<2;finish++) {
        reset();early_kind=early;ap_mode=early==4;immediate=sync;finish_early=finish;run();
        assert(submitted==(early==0));cases++;
    }
    for(unsigned mode=0;mode<4;mode++)for(unsigned sync=0;sync<2;sync++) {
        reset();immediate=sync;cancelled=mode==0;submit_error=mode==1;push_error=mode==2;ability_disabled=mode==3;run();
        assert(submitted==(mode==2));cases++;
    }
    for(unsigned cb=0;cb<2;cb++)for(unsigned fail=1;fail<=4;fail++) {
        reset();fail_at=fail;mtlk_df_t df={.vap_handle=&core_obj};struct mgmt_tx_params p={0};
        _mtlk_df_user_invoke_core_async(&df,7,&p,sizeof(p),cb?empty_done:NULL,0);
        assert(!queued_req && !live_allocs && notify_calls==cb);cases++;
    }
    for(unsigned cb=0;cb<2;cb++)for(unsigned sync=0;sync<2;sync++) {
        reset();immediate=sync;cancelled=1;mtlk_df_t df={.vap_handle=&core_obj};struct mgmt_tx_params p={0};
        _mtlk_df_user_invoke_core_async(&df,7,&p,sizeof(p),cb?empty_done:NULL,0);
        if(queued_req)dispatch();
        assert(!live_allocs && notify_calls==cb);cases++;
    }
    for(unsigned ap=0;ap<2;ap++)for(unsigned ack=0;ack<2;ack++)for(unsigned skb=0;skb<2;skb++) {
        reset();ap_mode=ap;struct sk_buff *s=skb?packet():NULL;
        assert(drop_frame(&core_obj,s,!ack)==MTLK_ERR_NOT_HANDLED);
        assert(live_skbs==skb && !statuses && !drops && !notify_calls);
        if(s)consume(s);cases++;
    }
    reset();printf("PASS: %u deferred management ownership, failure/cancellation, no-callback allocation and frame-drop cases (modeled kernel/serializer/firmware leaves)\n",cases);
    drain_scenarios();lifetime_destroy();
}
'''
for key,value in [('PARAMS',params),('LIFETIME_STRUCT',lifetime_struct),('LIFETIME_HELPERS',lifetime_helpers),('UNREGISTER',unregister),('ASYNC_CTX',async_ctx),('ASYNC_FUNCS',async_funcs),('OWNER',owner),('MAC_TX',mac_tx),('CLIP_MACROS',macros),('CORE_TX',core_tx),('CORE_DISPATCH',core_dispatch),('DROP_BODY',drop)]:h=h.replace('\n'+key+'\n','\n'+value+'\n')
h=h.replace('TEST_CASE',a.case)
def run(path):
    path.mkdir(parents=True,exist_ok=True);(path/'probe.c').write_text(h)
    flags=['-static'] if a.qemu else ['-fno-pie','-no-pie','-fsanitize=address,undefined']
    subprocess.run([a.cc,'-std=gnu11','-O1','-g','-pthread',*flags,str(path/'probe.c'),'-o',str(path/'probe')],check=True)
    cmd=[str(path/'probe')]
    if a.qemu:cmd.insert(0,str(a.qemu.resolve()))
    env=os.environ.copy();env['ASAN_OPTIONS']='detect_stack_use_after_return=1'
    subprocess.run(cmd,check=True,cwd=path,env=env)
if a.output:run(a.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-async-mgmt-') as tmp:run(Path(tmp))
