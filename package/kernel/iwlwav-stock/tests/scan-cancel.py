#!/usr/bin/env python3
"""Exercise the driver's real scan-cancel callbacks with modeled timer/serializer leaves."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tree', type=Path)
p.add_argument('--cc', default='gcc')
p.add_argument('--qemu', type=Path)
p.add_argument('--output', type=Path)
a = p.parse_args()
scan = (a.tree / 'wireless/driver/shared/scan_support.c').read_text()
mac = (a.tree / 'wireless/driver/linux/mac80211.c').read_text()

def extract(source, name):
    m = re.search(r'^(?:static\s+)?(?:BOOL|void|uint32|int)\s+(?:__MTLK_IFUNC\s+)?'
                  + name + r'\s*\([^;]*?\)\s*\{', source, re.M)
    assert m, name
    end, depth = m.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[m.start():end]

functions = '\n'.join(extract(scan, name) for name in
                      ('scan_support_channel_request_enter',
                       'scan_support_channel_request_exit',
                       'scan_support_channel_requests_idle',
                       'scan_timer_clb_func', 'sched_scan_timer_clb_func',
                       'cac_timer_clb_func', 'cac_timer_serialized_func',
                       'abort_scan',
                       'scan_support_prepare_remove',
                       'clean_up_after_this_scan'))
functions += '\n' + extract(mac, '_wv_ieee80211_op_cancel_hw_scan')
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define TRUE 1
#define MTLK_ERR_OK 0
#define WAVE_RADIO_REQ_SCAN_TIMEOUT 17
#define WAVE_RADIO_REQ_CAC_TIMEOUT 18
#define WAVE_RADIO_REQ_DO_SCAN 19
#define WAVE_RADIO_REQ_SET_CHAN 20
#define SDF_RUNNING 1
#define SDF_ABORT 2
#define HANDLE_T(x) ((mtlk_handle_t)(x))
#define MTLK_ASSERT(x) assert(x)
#define MTLK_UNREFERENCED_PARAM(x) ((void)(x))
#define ILOG0_V(...) ((void)0)
#define ILOG0_S(...) ((void)0)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define WARN_ON_ONCE(x) (x)
#define wmb() ((void)0)
typedef unsigned uint32;
typedef int BOOL;
typedef uintptr_t mtlk_handle_t;
typedef int spinlock_t;
typedef int wait_queue_head_t;
#define spin_lock_irqsave(lock,flags) do {(void)(lock);(flags)=0;}while(0)
#define spin_unlock_irqrestore(lock,flags) do {(void)(lock);(void)(flags);}while(0)
#define wake_up_all(wait) ((void)(wait))
#define wait_event(wait,condition) do {(void)(wait);assert(condition);}while(0)
typedef struct { unsigned armed; } mtlk_osal_timer_t;
typedef void mtlk_df_t;
typedef void mtlk_df_user_t;
typedef void mtlk_clpb_t;
struct net_device { int dummy; };
struct mtlk_chan_def { unsigned center_freq1; };
struct set_chan_param_data {
    struct mtlk_chan_def chandef;
    struct net_device *ndev;
    int vap_id,dont_notify_kernel;
};
struct mtlk_scan_request { uint32 interval; };
typedef struct {
    mtlk_osal_timer_t sched_scan_timer,cac_timer;
    struct mtlk_scan_request *sched_scan_req;
} slow_ctx_t;
typedef struct { int radar_unblocked; } wave_radio_t;
typedef struct { void *data; } mtlk_txmm_msg_t;
typedef struct scan_support {
    int flags,removal_pending;
    spinlock_t channel_req_lock;
    wait_queue_head_t channel_req_wait;
    unsigned channel_req_users;
    mtlk_osal_timer_t scan_timer;
    struct mtlk_core *master_core;
    struct mtlk_chan_def orig_chandef;
    mtlk_txmm_msg_t set_chan_man_msg;
    void *probe_req;
    unsigned probe_req_len;
    int last_chan_idx,chan_in_chunk;
    struct { int switch_in_progress; } dfs_debug_params;
} mtlk_scan_support_t;
typedef struct mtlk_core {
    void *vap_handle;mtlk_scan_support_t *scan;
    struct mtlk_chan_def current_chandef;
    slow_ctx_t *slow_ctx;
} mtlk_core_t;
typedef struct { mtlk_scan_support_t *scan; } wv_mac80211_t;
struct ieee80211_hw { wv_mac80211_t *mac; };
struct ieee80211_vif { int dummy; };
static unsigned queued,completed,canceled,cases,wiphy_locked,inside_serializer;
static unsigned cac_queued,cac_canceled,sched_canceled,timer_set_calls,scheduled_invokes;
static unsigned set_chan_queued,cac_events,radar_waits,block_tx_set_calls;
static int mark_removal_during_invoke;
static int mark_removal_during_radar_wait,block_tx;
static unsigned set_channel_calls,txmm_cleanup_calls,probe_free_calls;
static int fatal_pending;
static mtlk_core_t core;
static mtlk_scan_support_t ss;
static slow_ctx_t slow_ctx;
static wave_radio_t radio;
static struct net_device ndev;
static wv_mac80211_t mac;
static struct ieee80211_hw hw;
static void *mtlk_vap_get_manager(void *vap) { return vap; }
static mtlk_core_t *mtlk_vap_manager_get_master_core(void *mgr) { (void)mgr;return &core; }
static void *mtlk_vap_get_hw(void *vap) { return vap; }
static void *mtlk_vap_get_df(void *vap) { return vap; }
static mtlk_df_user_t *mtlk_df_get_user(mtlk_df_t *df) { return df; }
static struct net_device *mtlk_df_user_get_ndev(mtlk_df_user_t *user) {
    (void)user;return &ndev;
}
static void *mtlk_df_get_vap_handle(mtlk_df_t *df) { return df; }
static int mtlk_vap_get_id(void *vap) { (void)vap;return 2; }
static mtlk_core_t *mtlk_core_get_master(mtlk_core_t *c) { return c; }
static mtlk_scan_support_t *mtlk_core_get_scan_support(mtlk_core_t *c) { return c->scan; }
static void *mtlk_vap_manager_get_master_df(void *mgr) { return mgr; }
static wave_radio_t *wave_vap_radio_get(void *vap) { (void)vap;return &radio; }
static void wave_radio_on_rcvry_isolate(wave_radio_t *r) { r->radar_unblocked=1; }
static void wave_radio_radar_detect_end_wait(wave_radio_t *r) {
    (void)r;radar_waits++;
    if(mark_removal_during_radar_wait)ss.removal_pending=1;
}
static void wv_cfg80211_cac_event(struct net_device *dev,
                                   struct mtlk_chan_def *cd,int ok) {
    assert(dev==&ndev && cd==&core.current_chandef && ok);cac_events++;
}
static int mtlk_core_cfg_get_block_tx(mtlk_core_t *c) { (void)c;return block_tx; }
static void mtlk_core_cfg_set_block_tx(mtlk_core_t *c,int value) {
    (void)c;assert(!value);block_tx_set_calls++;
}
static const char *mtlk_df_get_name(mtlk_df_t *df) { (void)df;return "scan"; }
static mtlk_scan_support_t *__wave_core_scan_support_get(mtlk_core_t *c) { return c->scan; }
static struct mtlk_chan_def *__wave_core_chandef_get(mtlk_core_t *c) {
    return &c->current_chandef;
}
static int is_channel_certain(struct mtlk_chan_def *cd) { return cd->center_freq1!=0; }
static int core_cfg_set_chan(mtlk_core_t *c,struct mtlk_chan_def *cd,void *unused) {
    (void)c;(void)cd;(void)unused;assert(!ss.removal_pending);set_channel_calls++;return 0;
}
static void mtlk_txmm_msg_cleanup(mtlk_txmm_msg_t *m) { assert(m->data);txmm_cleanup_calls++; }
static void mtlk_osal_mem_free(void *p) { assert(p);probe_free_calls++; }
static int wave_rcvry_mac_fatal_pending_get(void *unused) { (void)unused;return fatal_pending; }
static void _mtlk_df_user_invoke_core_async(void *df,unsigned req,void *a,
                                             unsigned b,void *c,unsigned d) {
    (void)df;(void)a;(void)b;(void)c;(void)d;
    if(req==WAVE_RADIO_REQ_SCAN_TIMEOUT) queued++;
    else if(req==WAVE_RADIO_REQ_CAC_TIMEOUT)cac_queued++;
    else { assert(req==WAVE_RADIO_REQ_SET_CHAN);set_chan_queued++; }
}
static int _mtlk_df_user_invoke_core(void *df,unsigned req,mtlk_clpb_t **clpb,
                                      void *data,unsigned size) {
    (void)df;assert(req==WAVE_RADIO_REQ_DO_SCAN && clpb && data);
    assert(size==sizeof(struct mtlk_scan_request));*clpb=NULL;scheduled_invokes++;
    if(mark_removal_during_invoke) ss.removal_pending=1;
    return MTLK_ERR_OK;
}
static int _mtlk_df_user_process_core_retval_void(int res,mtlk_clpb_t *clpb,
                                                    unsigned req,int flag) {
    (void)clpb;assert(req==WAVE_RADIO_REQ_DO_SCAN && flag);return res;
}
static int is_scan_running(mtlk_scan_support_t *s) { return !!(s->flags & SDF_RUNNING); }
static void mtlk_osal_timer_cancel_sync(mtlk_osal_timer_t *t) {
    assert(!inside_serializer);
    t->armed=0;
    if(t==&ss.scan_timer)canceled++;
    else if(t==&slow_ctx.cac_timer){assert(radio.radar_unblocked);cac_canceled++;}
    else {assert(t==&slow_ctx.sched_scan_timer && radio.radar_unblocked);sched_canceled++;}
}
static void mtlk_osal_timer_set(mtlk_osal_timer_t *t,uint32 interval) {
    assert(t==&slow_ctx.sched_scan_timer && interval && !inside_serializer);
    timer_set_calls++;t->armed=1;
}
static wv_mac80211_t *__wv_ieee80211_hw_get_mac80211(struct ieee80211_hw *h) { return h->mac; }
static struct scan_support *__wv_mac80211_scan_support_get(wv_mac80211_t *m) { return m->scan; }
FUNCTIONS
static void drain(void) {
    assert(!wiphy_locked);
    inside_serializer=1;
    while(queued) {
        queued--;
        if(ss.flags & SDF_RUNNING) {
            assert(ss.flags & SDF_ABORT);
            ss.flags=0;completed++;
        }
    }
    inside_serializer=0;
}
static void reset(void) {
    queued=completed=canceled=wiphy_locked=inside_serializer=0;
    cac_queued=cac_canceled=sched_canceled=timer_set_calls=scheduled_invokes=0;
    set_chan_queued=cac_events=radar_waits=block_tx_set_calls=0;
    mark_removal_during_invoke=mark_removal_during_radar_wait=block_tx=0;
    set_channel_calls=txmm_cleanup_calls=probe_free_calls=0;
    fatal_pending=0;
    ss=(mtlk_scan_support_t){.master_core=&core};
    slow_ctx=(slow_ctx_t){0};radio=(wave_radio_t){0};
    core=(mtlk_core_t){.vap_handle=&core,.scan=&ss,.slow_ctx=&slow_ctx};
    mac=(wv_mac80211_t){.scan=&ss};
    hw=(struct ieee80211_hw){.mac=&mac};
}
int main(void) {
    struct ieee80211_vif vif={0};
    for(int fatal=0;fatal<2;fatal++) for(int removal=0;removal<2;removal++) {
        reset();fatal_pending=fatal;
        if(removal) scan_support_prepare_remove(&ss);
        scan_timer_clb_func(&ss.scan_timer,HANDLE_T(&core));
        assert(queued==(unsigned)(!fatal || removal));cases++;
    }
    for(int fatal=0;fatal<2;fatal++) for(int removal=0;removal<2;removal++) {
        reset();fatal_pending=fatal;ss.flags=SDF_RUNNING;ss.scan_timer.armed=1;
        if(removal) scan_support_prepare_remove(&ss);
        wiphy_locked=1;
        _wv_ieee80211_op_cancel_hw_scan(&hw,&vif);
        assert(!ss.scan_timer.armed && canceled==1);
        assert(ss.flags & SDF_ABORT);
        assert(queued==(unsigned)(!fatal || removal));
        wiphy_locked=0;
        if(removal || !fatal) { drain();assert(completed==1); }
        else assert(completed==0);
        cases++;
    }
    reset();
    _wv_ieee80211_op_cancel_hw_scan(&hw,&vif);
    assert(!queued && !completed && !canceled);cases++;
    reset();ss.flags=SDF_RUNNING;ss.scan_timer.armed=1;
    _wv_ieee80211_op_cancel_hw_scan(&hw,&vif);
    _wv_ieee80211_op_cancel_hw_scan(&hw,&vif);
    drain();assert(completed==1 && canceled==2);cases++;
    for(int removal=0;removal<2;removal++) {
        reset();ss.orig_chandef.center_freq1=5180;
        ss.set_chan_man_msg.data=&ss;ss.probe_req=&ss;ss.probe_req_len=12;
        ss.flags=SDF_RUNNING;ss.last_chan_idx=3;ss.chan_in_chunk=2;
        if(removal) scan_support_prepare_remove(&ss);
        assert(clean_up_after_this_scan(&core,&ss)==0);
        assert(set_channel_calls==(unsigned)!removal);
        assert(txmm_cleanup_calls==1 && probe_free_calls==1);
        assert(!ss.set_chan_man_msg.data && !ss.probe_req && !ss.flags);
        assert(ss.last_chan_idx==-1 && !ss.chan_in_chunk);
        cases++;
    }
    for(int removal=0;removal<2;removal++) {
        struct mtlk_scan_request req={.interval=47};
        reset();slow_ctx.sched_scan_req=&req;
        if(removal) scan_support_prepare_remove(&ss);
        assert(sched_scan_timer_clb_func(NULL,HANDLE_T(&core))==0);
        assert(scheduled_invokes==(unsigned)!removal);
        assert(timer_set_calls==(unsigned)!removal);
        assert(slow_ctx.sched_scan_timer.armed==(unsigned)!removal);
        cases++;
    }
    reset();
    struct mtlk_scan_request req={.interval=47};slow_ctx.sched_scan_req=&req;
    inside_serializer=1;
    assert(sched_scan_timer_clb_func(&slow_ctx.sched_scan_timer,HANDLE_T(&core))==47);
    inside_serializer=0;
    assert(scheduled_invokes==1 && !timer_set_calls && !sched_canceled);cases++;
    reset();slow_ctx.sched_scan_req=&req;mark_removal_during_invoke=1;
    inside_serializer=1;
    assert(sched_scan_timer_clb_func(&slow_ctx.sched_scan_timer,HANDLE_T(&core))==0);
    inside_serializer=0;
    assert(scheduled_invokes==1 && !timer_set_calls);cases++;
    for(int removal=0;removal<2;removal++) {
        reset();
        if(removal) scan_support_prepare_remove(&ss);
        assert(cac_timer_clb_func(&slow_ctx.cac_timer,HANDLE_T(&core))==0);
        assert(cac_queued==(unsigned)!removal);
        if(removal)assert(radio.radar_unblocked && cac_canceled==1 && sched_canceled==1);
        cases++;
    }
    reset();
    assert(cac_timer_serialized_func(HANDLE_T(&core),NULL,0)==0);
    assert(radar_waits==1 && cac_events==1 && set_chan_queued==1);
    assert(block_tx_set_calls==1);cases++;
    reset();scan_support_prepare_remove(&ss);
    assert(cac_timer_serialized_func(HANDLE_T(&core),NULL,0)==0);
    assert(!radar_waits && !cac_events && !set_chan_queued);cases++;
    reset();mark_removal_during_radar_wait=1;
    assert(cac_timer_serialized_func(HANDLE_T(&core),NULL,0)==0);
    assert(radar_waits==1 && !cac_events && !set_chan_queued);cases++;
    printf("PASS: %u scan-cancel/timer cases (modeled timer and serializer)\n",cases);
}
'''.replace('FUNCTIONS', functions)
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / 'scan-cancel.c'
    exe = a.output or Path(tmp) / 'scan-cancel'
    src.write_text(harness)
    cmd = [a.cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror',
           '-Wno-unused-parameter', '-O1', '-g',
           str(src), '-o', str(exe)]
    if a.qemu:
        cmd[1:1] = ['-static']
    if not a.qemu and a.cc == 'gcc':
        cmd[1:1] = ['-fno-pie', '-no-pie', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer']
    subprocess.run(cmd, check=True)
    subprocess.run(([str(a.qemu)] if a.qemu else []) + [str(exe)], check=True)
