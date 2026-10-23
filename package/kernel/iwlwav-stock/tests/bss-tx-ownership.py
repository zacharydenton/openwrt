#!/usr/bin/env python3
"""Exercise BSS TX DMA helpers, buffer cleanup and the completion ownership block.

DMA, mac80211/cfg80211 callbacks and device objects are fixtures. This does
not execute firmware, IRQ synchronization, complete recovery or RF traffic.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tree', type=Path)
p.add_argument('--before', type=Path)
p.add_argument('--case', choices=('all', 'free', 'completion', 'pending'), default='all')
p.add_argument('--cc', default='gcc')
p.add_argument('--qemu', type=Path)
p.add_argument('--output', type=Path)
a = p.parse_args()
current = (a.tree / 'wireless/driver/shared/hw_mmb.c').read_text()
source = a.before.read_text() if a.before else current

def extract(text, name):
    match = re.search(r'^(?:static )?(?:void|int)(?: __MTLK_IFUNC)?\s*\n?' + name + r'\s*\([^;]*?\)\s*\{', text, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end]

# Before runs retain current setup helpers but execute the old free function
# or old completion block. They reproduce the specific ownership faults.
helpers = '\n'.join(extract(current, n) for n in (
    'wave_bss_tx_map', 'wave_bss_tx_unmap', '_mtlk_mmb_unmap_bss_tx_buffers',
    'wave_bss_tx_release_packets', 'mtlk_hw_mmb_release_bss_tx',
    '_mtlk_hw_mmb_wait_packet_completions', 'mtlk_hw_mmb_quiesce_mac80211'))
restore = extract(source, 'mtlk_hw_mmb_restore')
release_start = restore.index('  _mtlk_mmb_free_preallocated_rx_mgmt_buffers(hw);')
release_start = restore.index('\n', release_start) + 1
restore_release = restore[release_start:restore.index('  _mtlk_mmb_cleanup_dbg_ind_bdr', release_start)]
cleanup = extract(source, 'mtlk_mmb_free_bss_tx_buffers')
completion = extract(source, '_mtlk_mmb_handle_bss_cfm')
start = re.search(r'^  (?:wave_bss_tx_unmap|mtlk_osal_unmap_phys_addr)\(', completion, re.M).start()
completion = completion[start:completion.index("  /* Note that we don't use", start)]

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned uint32;
#define __MTLK_IFUNC
#define HW_FLAGS_PREPARED_BSS_REQ_BDR 1
#define HW_FLAGS_PREPARED_DATA_REQ_BDR 2
#define MTLK_ERR_OK 0
#define MTLK_ERR_UNKNOWN -1
#define MTLK_ERR_NO_MEM -2
#define MTLK_DATA_TO_DEVICE 1
#define PROCESS_MANAGEMENT 0
#define PROCESS_NULL_DATA_PACKET 1
#define PROCESS_EAPOL 2
#define GFP_ATOMIC 0
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,y) ((x)=(y))
#define MTLK_IRQ_ALL 0xffffffffU
#define MTLK_ASSERT(x) assert(x)
#define ILOG2_D(...) ((void)0)
#define WLOG_DD(...) ((void)0)
#define FALSE 0
typedef int BOOL;
struct sk_buff { unsigned id; };
typedef struct { unsigned char au8Addr[6]; } IEEE_ADDR;
struct mtlk_hw_bss_req_mirror {
    unsigned char *virt_addr;
    uint32 dma_addr,size;
    bool dma_mapped;
    uint64_t cookie;
    unsigned extra_processing;
    unsigned radio_id;
    unsigned subtype;
    BOOL is_broadcast;
    IEEE_ADDR dst_addr;
    struct sk_buff *skb;
};
struct basic { unsigned nof_bds; struct mtlk_hw_bss_req_mirror slots[4]; };
typedef struct { struct basic basic; unsigned lock,used_list; } mtlk_mmb_advanced_bdr_t;
typedef unsigned long mtlk_handle_t;
typedef struct { void *ccr; unsigned flags,reg_lock;
    unsigned mac_events_stopped,mac_events_stopped_completely;
    struct { struct { unsigned lock,used_list; } bdr_data; } tx;
    struct { mtlk_mmb_advanced_bdr_t tx_bdr,tx_res_bdr; } bss_mgmt;
} mtlk_hw_t;
typedef struct { unsigned id; } wave_radio_t;
struct ieee80211_hw { unsigned live; };
struct wireless_dev { unsigned live; };
typedef struct { struct { unsigned char au8Addr[6]; } dst_addr; } frame_head_t;
static unsigned maps,unmaps,buffers,skbs,statuses,ap_statuses,probes;
static unsigned next_addr,fail_map,is_ap;
static struct { unsigned active,addr,size; void *ptr; } mappings[8];
static struct ieee80211_hw mac_hw={1};
static struct wireless_dev wdev_obj={1};
static wave_radio_t radios[2]={{0},{1}};
static unsigned owner_missing, tx_drops, raw_drops;
static unsigned irq_quiesces, irq_resumes, hw_enables;
static unsigned wait_sleeps;
static mtlk_hw_t *wait_hw;
static unsigned mtlk_dlist_size(unsigned *list) { return *list; }
static void mtlk_osal_lock_acquire(unsigned *lock) { assert(lock); }
static void mtlk_osal_lock_release(unsigned *lock) { assert(lock); }
static void mtlk_osal_msleep(unsigned ms) {
    assert(ms==10 && wait_hw);wait_sleeps++;
    wait_hw->tx.bdr_data.used_list=0;
    wait_hw->bss_mgmt.tx_bdr.used_list=0;
    wait_hw->bss_mgmt.tx_res_bdr.used_list=0;
}
static void mtlk_mmb_drv_recovery_irq_quiesce(mtlk_hw_t *hw) {
    assert(hw->mac_events_stopped);irq_quiesces++;
}
static void mtlk_mmb_drv_recovery_irq_resume(mtlk_hw_t *hw) {
    assert(hw->mac_events_stopped && irq_quiesces);irq_resumes++;
}
static mtlk_handle_t mtlk_osal_lock_acquire_irq(unsigned *lock) { assert(lock);return 0; }
static void mtlk_osal_lock_release_irq(unsigned *lock,mtlk_handle_t val) { (void)val;assert(lock); }
static void mtlk_ccr_enable_interrupts(void *ccr,unsigned mask) {
    assert(ccr && mask==MTLK_IRQ_ALL);hw_enables++;
}
static void *mtlk_ccr_get_dev_ctx(void *ctx) { return ctx; }
static unsigned mtlk_osal_map_to_phys_addr(void *ctx,void *ptr,unsigned size,unsigned dir) {
    (void)ctx;assert(ptr && size && dir==1);
    if(fail_map) return UINT32_MAX;
    for(unsigned i=0;i<8;i++) if(!mappings[i].active) {
        mappings[i].active=1;mappings[i].addr=next_addr;mappings[i].size=size;mappings[i].ptr=ptr;
        maps++;return next_addr;
    }
    abort();
}
static int dma_mapping_error(void *ctx,unsigned addr) { (void)ctx;return addr==UINT32_MAX; }
static void mtlk_osal_unmap_phys_addr(void *ctx,unsigned addr,unsigned size,unsigned dir) {
    (void)ctx;assert(dir==1);
    for(unsigned i=0;i<8;i++) if(mappings[i].active && mappings[i].addr==addr) {
        assert(mappings[i].size==size);mappings[i].active=0;unmaps++;return;
    }
    fprintf(stderr,"unmap without active mapping: addr=%x\n",addr);abort();
}
static void mtlk_osal_mem_free(void *ptr) {
    for(unsigned i=0;i<8;i++) if(mappings[i].active && mappings[i].ptr==ptr) {
        fprintf(stderr,"freeing buffer while its DMA mapping is live\n");abort();
    }
    assert(buffers);buffers--;free(ptr);
}
static struct mtlk_hw_bss_req_mirror *lookup(struct basic *b,unsigned i) { assert(i<b->nof_bds);return &b->slots[i]; }
#define _mtlk_basic_bdr_get_mirror_bd(b,i,t) lookup(b,i)
static int mtlk_vap_is_ap(void *vap) { assert(vap);return is_ap; }
static void *mtlk_vap_get_df(void *vap) { assert(vap);return vap; }
static void *mtlk_df_get_user(void *df) { assert(df);return df; }
static void *mtlk_df_user_get_ndev(void *user) { assert(user);return user; }
static struct wireless_dev *mtlk_df_user_get_wdev(void *user) { assert(user);return &wdev_obj; }
static struct ieee80211_hw *wave_radio_ieee80211_hw_get(void *radio) { assert(radio);return owner_missing?NULL:&mac_hw; }
static wave_radio_t *__mtlk_hw_wave_radio_get(mtlk_hw_t *hw,unsigned id) { (void)hw;assert(id<2);return &radios[id]; }
static void ieee80211_free_txskb(struct ieee80211_hw *hw,struct sk_buff *skb) {
    assert(hw->live && skbs && skb);skbs--;tx_drops++;free(skb);
}
static void dev_kfree_skb_any(struct sk_buff *skb) { assert(skbs && skb);skbs--;raw_drops++;free(skb); }
static void wv_ieee80211_tx_status(struct ieee80211_hw *hw,struct sk_buff *skb,unsigned status) {
    (void)status;assert(hw->live && skb && skbs);statuses++;skbs--;free(skb);
}
static void cfg80211_mgmt_tx_status(struct wireless_dev *wdev,uint64_t cookie,void *buf,unsigned size,unsigned status,unsigned flags) {
    (void)status;(void)flags;assert(wdev->live && cookie && buf && size);ap_statuses++;
}
static void cfg80211_probe_status(void *dev,void *addr,uint64_t cookie,unsigned status,unsigned rate,bool ack,unsigned flags) {
    (void)addr;(void)cookie;(void)status;(void)rate;(void)ack;(void)flags;assert(dev);probes++;
}
HELPERS
CLEANUP
static void restore_release(mtlk_hw_t *hw) {
RESTORE_RELEASE
}
static void complete(mtlk_hw_t *hw,struct mtlk_hw_bss_req_mirror *bss_req) {
    struct wireless_dev *wdev;
    frame_head_t header={0},*wifi_header=&header;
    void *vap_handle=hw,*df_user=hw,*radio=hw,*ndev=hw,*df=hw;
    unsigned status=1;
    IEEE_ADDR confirmed_dst_addr;
    uint32 confirmed_extra_processing;
    unsigned char confirmed_subtype;
    BOOL confirmed_is_broadcast;
COMPLETION
}
static void reset(void) {
    assert(!buffers && !skbs);
    for(unsigned i=0;i<8;i++) assert(!mappings[i].active);
    maps=unmaps=statuses=ap_statuses=probes=fail_map=is_ap=0;next_addr=0x1000;
    owner_missing=tx_drops=raw_drops=irq_quiesces=irq_resumes=hw_enables=wait_sleeps=0;
}
static void alloc_req(struct mtlk_hw_bss_req_mirror *req,unsigned len) {
    memset(req,0,sizeof(*req));req->virt_addr=malloc(len);assert(req->virt_addr);
    req->size=len;buffers++;
}
static void cleanup_case(mtlk_hw_t *hw) {
    reset();mtlk_mmb_advanced_bdr_t b={.basic.nof_bds=4};
    alloc_req(&b.basic.slots[0],256);assert(!wave_bss_tx_map(hw,&b.basic.slots[0]));
    mtlk_mmb_free_bss_tx_buffers(hw,&b);assert(!buffers && maps==unmaps);
}
static void completion_case(mtlk_hw_t *hw) {
    reset();mtlk_mmb_advanced_bdr_t b={.basic.nof_bds=1};
    struct mtlk_hw_bss_req_mirror *r=&b.basic.slots[0];alloc_req(r,128);
    r->cookie=4;r->extra_processing=PROCESS_MANAGEMENT;
    r->skb=malloc(sizeof(*r->skb));assert(r->skb);skbs++;
    assert(!wave_bss_tx_map(hw,r));complete(hw,r);
    if(r->skb) fprintf(stderr,"completion leaves consumed skb pointer in descriptor\n");
    assert(!r->skb && !r->dma_mapped && !r->dma_addr && statuses==1);
    mtlk_mmb_free_bss_tx_buffers(hw,&b);assert(unmaps==1);
}
static void pending_case(mtlk_hw_t *hw,unsigned missing,unsigned count) {
    reset();memset(hw,0,sizeof(*hw));owner_missing=missing;
    hw->flags=HW_FLAGS_PREPARED_BSS_REQ_BDR;
    hw->bss_mgmt.tx_bdr.basic.nof_bds=hw->bss_mgmt.tx_res_bdr.basic.nof_bds=4;
    for(unsigned queue=0;queue<2;queue++) for(unsigned i=0;i<count;i++) {
        struct mtlk_hw_bss_req_mirror *r=queue?&hw->bss_mgmt.tx_res_bdr.basic.slots[i]:&hw->bss_mgmt.tx_bdr.basic.slots[i];
        alloc_req(r,128);r->radio_id=i%2;r->cookie=55;
        r->skb=malloc(sizeof(*r->skb));assert(r->skb);skbs++;
        if(!queue) { next_addr=i*0x1000;assert(!wave_bss_tx_map(hw,r)); }
    }
    restore_release(hw);
    if(skbs) fprintf(stderr,"Recovery leaves %u pending management skbs\n",skbs);
    assert(!skbs && maps==unmaps);
    assert(tx_drops==(missing?0:2*count) && raw_drops==(missing?2*count:0));
    for(unsigned i=0;i<4;i++) {
        assert(!hw->bss_mgmt.tx_bdr.basic.slots[i].skb && !hw->bss_mgmt.tx_bdr.basic.slots[i].cookie);
        assert(!hw->bss_mgmt.tx_res_bdr.basic.slots[i].skb && !hw->bss_mgmt.tx_res_bdr.basic.slots[i].cookie);
    }
    restore_release(hw);assert(tx_drops+raw_drops==2*count && unmaps==count);
    mtlk_mmb_free_bss_tx_buffers(hw,&hw->bss_mgmt.tx_bdr);
    mtlk_mmb_free_bss_tx_buffers(hw,&hw->bss_mgmt.tx_res_bdr);
}
static void unregister_case(mtlk_hw_t *hw,unsigned ap,unsigned isolated) {
    reset();memset(hw,0,sizeof(*hw));is_ap=ap;hw->ccr=hw;
    hw->flags=HW_FLAGS_PREPARED_BSS_REQ_BDR;
    hw->mac_events_stopped_completely=isolated;
    hw->bss_mgmt.tx_bdr.basic.nof_bds=hw->bss_mgmt.tx_res_bdr.basic.nof_bds=1;
    struct mtlk_hw_bss_req_mirror *main=&hw->bss_mgmt.tx_bdr.basic.slots[0];
    struct mtlk_hw_bss_req_mirror *reserve=&hw->bss_mgmt.tx_res_bdr.basic.slots[0];
    alloc_req(main,128);alloc_req(reserve,128);
    main->extra_processing=reserve->extra_processing=PROCESS_NULL_DATA_PACKET;
    main->cookie=reserve->cookie=55;
    main->skb=malloc(sizeof(*main->skb));reserve->skb=malloc(sizeof(*reserve->skb));
    assert(main->skb && reserve->skb);skbs=2;
    assert(!wave_bss_tx_map(hw,main));
    if(isolated) hw->bss_mgmt.tx_bdr.used_list=1;
    mtlk_hw_mmb_quiesce_mac80211(hw);
    assert(hw->mac_events_stopped && irq_quiesces==1 && irq_resumes==!isolated && hw_enables==!isolated);
    assert(!wait_sleeps);
    assert(!skbs && tx_drops==2 && !main->cookie && !reserve->cookie);
    assert(maps==1 && unmaps==0 && main->dma_mapped);
    if(!isolated) {
        complete(hw,main);
        assert(!statuses && !ap_statuses && !probes && unmaps==1);
    }
    mtlk_hw_mmb_release_bss_tx(hw);assert(maps==unmaps);
    mtlk_mmb_free_bss_tx_buffers(hw,&hw->bss_mgmt.tx_bdr);
    mtlk_mmb_free_bss_tx_buffers(hw,&hw->bss_mgmt.tx_res_bdr);
}
static void wait_case(mtlk_hw_t *hw) {
    reset();memset(hw,0,sizeof(*hw));wait_hw=hw;
    hw->flags=HW_FLAGS_PREPARED_DATA_REQ_BDR|HW_FLAGS_PREPARED_BSS_REQ_BDR;
    hw->tx.bdr_data.used_list=1;
    hw->bss_mgmt.tx_bdr.used_list=1;
    hw->bss_mgmt.tx_res_bdr.used_list=1;
    _mtlk_hw_mmb_wait_packet_completions(hw);
    assert(wait_sleeps==1 && !hw->tx.bdr_data.used_list && !hw->bss_mgmt.tx_bdr.used_list &&
           !hw->bss_mgmt.tx_res_bdr.used_list);
    wait_hw=NULL;
}
int main(void) {
    unsigned cases=0;mtlk_hw_t hw={0};
    if(!strcmp("CASE","free")) { cleanup_case(&hw);return 0; }
    if(!strcmp("CASE","completion")) { completion_case(&hw);return 0; }
    if(!strcmp("CASE","pending")) { pending_case(&hw,0,1);return 0; }
    cleanup_case(&hw);completion_case(&hw);cases+=2;
    for(unsigned addr=0;addr<2;addr++) for(unsigned count=0;count<=4;count++) {
        reset();mtlk_mmb_advanced_bdr_t b={.basic.nof_bds=4};
        for(unsigned i=0;i<count;i++) {
            alloc_req(&b.basic.slots[i],64+i*64);next_addr=addr*0x1000+i*0x100;
            assert(!wave_bss_tx_map(&hw,&b.basic.slots[i]));
        }
        _mtlk_mmb_unmap_bss_tx_buffers(&hw,&b);assert(unmaps==count);
        _mtlk_mmb_unmap_bss_tx_buffers(&hw,&b);assert(unmaps==count);
        mtlk_mmb_free_bss_tx_buffers(&hw,&b);assert(!buffers && unmaps==count);
        mtlk_mmb_free_bss_tx_buffers(&hw,&b);assert(!buffers && unmaps==count);cases++;
    }
    for(unsigned failed=0;failed<2;failed++) {
        reset();mtlk_mmb_advanced_bdr_t b={.basic.nof_bds=1};
        struct mtlk_hw_bss_req_mirror *r=&b.basic.slots[0];alloc_req(r,128);fail_map=failed;
        assert(wave_bss_tx_map(&hw,r)==(failed?MTLK_ERR_NO_MEM:MTLK_ERR_OK));
        if(failed) assert(!r->dma_mapped && !r->dma_addr && !maps);
        else {
            assert(wave_bss_tx_map(&hw,r)==MTLK_ERR_UNKNOWN && maps==1);
            wave_bss_tx_unmap(&hw,r);assert(!wave_bss_tx_map(&hw,r));
        }
        mtlk_mmb_free_bss_tx_buffers(&hw,&b);assert(unmaps==maps);cases++;
    }
    for(unsigned ap=0;ap<2;ap++) for(unsigned kind=0;kind<3;kind++) for(unsigned addr=0;addr<2;addr++)
    for(unsigned cookie=0;cookie<2;cookie++) for(unsigned packet=0;packet<2;packet++) {
        reset();is_ap=ap;next_addr=addr*0x1000;
        mtlk_mmb_advanced_bdr_t b={.basic.nof_bds=1};struct mtlk_hw_bss_req_mirror *r=&b.basic.slots[0];
        alloc_req(r,128);r->cookie=cookie?4:0;r->extra_processing=kind;
        if(packet) { r->skb=malloc(sizeof(*r->skb));assert(r->skb);skbs++; }
        assert(!wave_bss_tx_map(&hw,r));complete(&hw,r);
        assert(!r->dma_mapped && !r->dma_addr && !r->skb && !skbs && unmaps==1);
        assert(statuses==(!ap && packet));
        assert(raw_drops==(ap && packet));
        assert(ap_statuses==(ap && kind==PROCESS_MANAGEMENT && cookie));
        assert(probes==(ap && kind==PROCESS_NULL_DATA_PACKET));
        mtlk_mmb_free_bss_tx_buffers(&hw,&b);assert(unmaps==1);cases++;
    }
    for(unsigned missing=0;missing<2;missing++) for(unsigned count=0;count<=4;count++) {
        pending_case(&hw,missing,count);cases++;
    }
    for(unsigned ap=0;ap<2;ap++) for(unsigned isolated=0;isolated<2;isolated++) {
        unregister_case(&hw,ap,isolated);cases++;
    }
    wait_case(&hw);cases++;
    reset();memset(&hw,0,sizeof(hw));mtlk_hw_mmb_release_bss_tx(&hw);cases++;
    printf("PASS: %u BSS TX mapping/cleanup/completion-block cases (mocked DMA and callbacks)\n",cases);
}
'''
for key,val in [('HELPERS',helpers),('CLEANUP',cleanup),('COMPLETION',completion),('RESTORE_RELEASE',restore_release)]:
    harness=harness.replace('\n'+key+'\n','\n'+val+'\n')
harness=harness.replace('"CASE"','"'+a.case+'"')

def run(path):
    path.mkdir(parents=True,exist_ok=True);(path/'probe.c').write_text(harness)
    flags=['-static'] if a.qemu else ['-fno-pie','-no-pie','-fsanitize=address,undefined']
    subprocess.run([a.cc,'-std=gnu11','-O1','-g',*flags,str(path/'probe.c'),'-o',str(path/'probe')],check=True)
    cmd=[str(path/'probe')]
    if a.qemu:cmd.insert(0,str(a.qemu.resolve()))
    subprocess.run(cmd,check=True,cwd=path)
if a.output:run(a.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-bss-tx-') as tmp:run(Path(tmp))
