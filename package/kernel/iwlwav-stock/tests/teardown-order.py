#!/usr/bin/env python3
"""Run real IRQ/lifecycle functions with modeled IRQ/tasklet/resource leaves.

The cleanup-step fixture preserves the vendor's strict reverse-order bitmask
assertion. It does not run kernel IRQ synchronization, firmware or workers.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('tree',type=Path)
p.add_argument('--before',type=Path)
p.add_argument('--case',choices=('all','order','irq'),default='all')
p.add_argument('--cc',default='gcc')
p.add_argument('--qemu',type=Path)
p.add_argument('--output',type=Path)
a=p.parse_args()
root=a.before or a.tree
drv=(root/'wireless/driver/linux/mtlk_mmb_drv.c').read_text()
radio=(root/'wireless/driver/linux/wave_radio.c').read_text()

def extract(source,name):
    m=re.search(r'^(?:static\s+)?(?:void|int)\s+(?:__MTLK_IFUNC\s+)?'+name+r'\s*\([^;]*?\)\s*\{',source,re.M)
    assert m,name
    end,depth=m.end(),1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[m.start():end]

steps=re.findall(r'MTLK_INIT_STEPS_LIST_ENTRY\(mmb_drv, (\w+)\)',drv)
enum='enum { '+', '.join('STEP_'+n for n in steps)+', STEP_COUNT };'
functions=extract(drv,'_mmb_drv_drain_tasklets')+'\n' if '_mmb_drv_drain_tasklets(' in drv else ''
functions+='\n'.join(extract(drv,n) for n in ['_mmb_drv_irq_stop','_mmb_drv_irq_start','kill_all_tasklets'])
if '_mmb_drv_quiesce_irqs(' in drv:functions+='\n'+extract(drv,'_mmb_drv_quiesce_irqs')
functions+='\n'+extract(drv,'init_all_tasklets')
functions+='\n'+'\n'.join(extract(radio,n) for n in ['_wave_radio_mac80211_deinit','wave_radio_mac80211_deinit','_wave_radio_deinit','wave_radio_deinit'])
functions+='\n'+extract(radio,'wave_radio_mac80211_tx_quiesce')
if 'wave_radio_scan_quiesce(' in radio:
    if 'mtlk_core_scan_quiesce(' not in extract(radio,'wave_radio_scan_quiesce'):
        functions+='\n'+extract(radio,'_wave_radio_abort_and_prevent_scan')
    functions+='\n'+extract(radio,'wave_radio_scan_quiesce')
if '_mmb_drv_mac80211_deinit(' in drv:functions+='\n'+extract(drv,'_mmb_drv_mac80211_deinit')
functions+='\n'+extract(drv,'_mmb_drv_cleanup')
harness=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MTLK_ASSERT(x) assert(x)
#define MTLK_ERR_OK 0
#define MTLK_ERR_UNKNOWN -1
#define TRUE 1
#define MTLK_IRQ_MODE_LEGACY 0
#define MTLK_IRQ_NONE 0
#define MTCFG_LINDRV_HW_PCIEG6
#define MTCFG_BUS_PCI_PCIE
#define IRQF_SHARED 0
#define DRV_NAME "fixture"
#define ELOG_D(...) ((void)0)
#define ELOG_DD(...) ((void)0)
#define ELOG_V(...) ((void)0)
#define ILOG2_SDD(...) ((void)0)
#define BIT(i) (1UL<<(i))
typedef int BOOL;
typedef int wave_int;
typedef uintptr_t mtlk_handle_t;
typedef void tasklet_func(unsigned long);
typedef struct { int id,live; } tasklet;
typedef struct { void *hw; tasklet *irq_tasklets; int status,irq_no; } mtlk_irq_handler_data;
typedef struct { int allocated,registered; } mac_owner;
typedef struct wave_radio { mac_owner *mac80211; int init_done,scan_removed; struct wave_radio *master_core; } wave_radio_t;
typedef struct { int num_radios;wave_radio_t radio[2]; } wave_radio_descr_t;
typedef struct { void *hw; } hw_api;
typedef struct {
    hw_api *hw_api;void *bar1;int ccr,nof_irqs,irq_mode,irq_out[6],irq_in[6];
    mtlk_irq_handler_data irq_handler_data[6];
    tasklet irq_tasklet[6],irq_tasklets_global[1];
    mtlk_irq_handler_data *ihd_pending;
    unsigned long requested_irqs, recovery_disabled_irqs;
    bool tasklets_initialized;
} mtlk_mmb_drv_t;
static mtlk_mmb_drv_t *active;
static wave_radio_descr_t radios;
static mac_owner owners[2];
static unsigned long external_irqs,active_steps;
static unsigned required_mask,irq_masks,resets,pending,packet_drops,rtnl_depth,freed_owners;
static int fail_irq,irq_enabled;
ENUM
#define MTLK_OBJ_PTR(x) (x)
#define MTLK_CLEANUP_BEGIN(m,o) {
#define MTLK_CLEANUP_END(m,o) assert(!active_steps); }
#define MTLK_CLEANUP_STEP(m,s,o,f,args) do { \
    if(active_steps & BIT(STEP_##s)) { f args;active_steps &= ~BIT(STEP_##s); \
      assert(active_steps==(BIT(STEP_##s)-1)); } \
} while(0)
#define MTLK_STOP_BEGIN(m,o) {
#define MTLK_STOP_END(m,o) }
#define MTLK_STOP_STEP(...) ((void)0)
#define MTLK_NOACTION(...) ((void)0)
static void dummy_tasklet(unsigned long x) { (void)x; }
static tasklet_func *tasklets_8[6]={dummy_tasklet,dummy_tasklet,dummy_tasklet,dummy_tasklet,dummy_tasklet,dummy_tasklet};
static tasklet_func *tasklets_4[4]={dummy_tasklet,dummy_tasklet,dummy_tasklet,dummy_tasklet};
static tasklet_func *tasklets_1[1]={dummy_tasklet};
static mtlk_irq_handler_data ihd_8[6]={{.irq_no=0},{.irq_no=1},{.irq_no=2},{.irq_no=3},{.irq_no=4},{.irq_no=5}};
static mtlk_irq_handler_data ihd_4[4]={{.irq_no=0},{.irq_no=1},{.irq_no=2},{.irq_no=3}};
static mtlk_irq_handler_data ihd_1[1]={{.irq_no=0}};
#define _on_interrupt_msi NULL
#define _on_interrupt_legacy NULL
static int _mmb_drv_is_irqno_required(void *hw,int n) { assert(hw);return !!(required_mask&BIT(n)); }
static void mtlk_hw_mmb_set_msi_intr_mode(void *hw,int mode) { (void)mode;assert(hw); }
static int request_irq(int irq,void *fn,unsigned flags,const char *name,void *data) {
    (void)fn;(void)flags;(void)name;(void)data;
    unsigned i=irq-10;assert(i<6 && !(external_irqs&BIT(i)));
    if((int)i==fail_irq) return -1;
    external_irqs|=BIT(i);return 0;
}
static void enable_irq(int irq) { (void)irq;abort(); } /* recovery not used by this fixture */
static void free_irq(int irq,void *data) {
    (void)data;unsigned i=irq-10;assert(external_irqs&BIT(i));external_irqs&=~BIT(i);
}
static void tasklet_init(tasklet *t,tasklet_func *fn,mtlk_handle_t data) { (void)fn;(void)data;assert(!t->live);t->live=1; }
static void tasklet_kill(tasklet *t) { assert(!external_irqs);t->live=0;irq_enabled=1; }
static void mtlk_hw_mmb_dis_interrupts(void *hw) { assert(hw);irq_enabled=0;irq_masks++; }
static void mtlk_hw_mmb_reset_mac(void *hw) {
    assert(hw && !external_irqs && !active->tasklets_initialized && !irq_enabled);resets++;
}
static void mtlk_hw_mmb_release_bss_tx(void *hw) {
    assert(hw && resets && !external_irqs && !active->tasklets_initialized);
    if(pending) assert(owners[0].allocated && owners[1].allocated);
    packet_drops+=pending;pending=0;
}
static unsigned quiesced_owners;
static unsigned scan_quiesced;
static unsigned dfs_quiesced;
typedef void mtlk_clpb_t;
typedef struct { int abort_scan,pause_or_prevent; } mtlk_alter_scan_t;
#define WAVE_RADIO_REQ_ALTER_SCAN 42
static void *wave_radio_df_get(wave_radio_t *radio) { assert(radio->init_done);return radio; }
static void *mtlk_df_get_user(void *df) { return df; }
static void mtlk_df_user_quiesce_prop_dfs_wq(void *user) {
    wave_radio_t *radio=user;assert(radio->init_done && !rtnl_depth);
    dfs_quiesced|=BIT(radio-radios.radio);
}
static wave_radio_t *wave_radio_scan_support_get(wave_radio_t *radio) { assert(radio->init_done);radio->master_core=radio;return radio; }
static void scan_support_prepare_remove(void *ss) { wave_radio_t *radio=ss;radio->scan_removed=1; }
static __attribute__((unused)) void mtlk_core_scan_quiesce(wave_radio_t *radio) {
    assert(radio->init_done && radio->scan_removed);
    scan_quiesced|=BIT(radio-radios.radio);
}
static int _mtlk_df_user_invoke_core(void *df,unsigned req,mtlk_clpb_t **clpb,void *data,unsigned len) {
    mtlk_alter_scan_t *alter=data;wave_radio_t *radio=df;
    assert(req==WAVE_RADIO_REQ_ALTER_SCAN && len==sizeof(*alter) && clpb);
    assert(alter->abort_scan && alter->pause_or_prevent && radio->init_done && radio->scan_removed);
    scan_quiesced|=BIT(radio-radios.radio);return MTLK_ERR_OK;
}
static int _mtlk_df_user_process_core_retval(int res,mtlk_clpb_t *clpb,unsigned req,int flag) {
    (void)clpb;assert(req==WAVE_RADIO_REQ_ALTER_SCAN && flag);return res;
}
static void wv_ieee80211_tx_quiesce(mac_owner *owner) {
    assert(owner->allocated && !rtnl_depth);quiesced_owners |= BIT(owner-owners);
}
static void wv_ieee80211_unregister(mac_owner *owner) {
    assert(owner->allocated && (quiesced_owners & BIT(owner-owners)) && !pending);owner->registered=0;
    assert(scan_quiesced & BIT(owner-owners));
    assert(dfs_quiesced & BIT(owner-owners));
}
static void wv_ieee80211_free(mac_owner *owner) {
    if(external_irqs || active->tasklets_initialized || pending)
        fprintf(stderr,"mac80211 freed before IRQ/tasklet/pending-TX drain\n");
    assert(owner->allocated && !owner->registered && !external_irqs && !active->tasklets_initialized && !pending);
    owner->allocated=0;freed_owners++;
}
static int mtlk_mmb_is_bcl(void) { return 0; }
static void _mmb_drv_bcl_drv_cleanup(mtlk_mmb_drv_t *obj) { (void)obj;abort(); }
#define wave_rcvry_pci_probe_error_set(...) ((void)0)
#define _mmb_drv_mac_assert(...) ((void)0)
#define wave_rcvry_enabled_get(...) 1
static wave_radio_descr_t *wave_card_radio_descr_get(void *hw) { assert(hw);return &radios; }
static void wave_rcvry_cleanup_finalize(void *hw) {
    assert(hw && !rtnl_depth);
    for(unsigned i=0;i<2;i++)if(owners[i].allocated)assert(quiesced_owners & BIT(i));
}
#define wave_hw_tx_stop(...) ((void)0)
static void mtlk_hw_mmb_quiesce_mac80211(void *hw) {
    assert(hw && !rtnl_depth && active->tasklets_initialized);
    if(pending) assert(owners[0].allocated && owners[1].allocated);
    packet_drops+=pending;pending=0;
}
#define wave_radio_prepare_stop(...) ((void)0)
#define mtlk_hw_mmb_stop_mac_events(...) ((void)0)
#define wave_radio_deinit_finalize(...) ((void)0)
#define mtlk_hw_mmb_stop_card_finalize(...) ((void)0)
static void rtnl_lock(void) { assert(!rtnl_depth);rtnl_depth++; }
static void rtnl_unlock(void) { assert(rtnl_depth==1);rtnl_depth--; }
static void mtlk_txmm_cleanup(void *p) { (void)p;assert(!external_irqs && !active->tasklets_initialized); }
#define mtlk_hw_mmb_get_txdm_base(hw) (hw)
#define mtlk_hw_mmb_get_txmm_base(hw) (hw)
static void mtlk_hw_mmb_stop_card(void *hw) { assert(hw && !external_irqs && !active->tasklets_initialized && !pending); }
#define mtlk_hw_mmb_cleanup_card(...) ((void)0)
#define wave_radio_destroy(...) ((void)0)
#define mtlk_eeprom_psdb_parse_stop(...) ((void)0)
#define mtlk_ccr_cleanup(...) ((void)0)
#define mtlk_hw_mmb_remove_card(...) ((void)0)
FUNCTIONS
static hw_api api;
static unsigned cases;
static void setup(mtlk_mmb_drv_t *obj,unsigned n,unsigned mask) {
    memset(obj,0,sizeof(*obj));memset(&radios,0,sizeof(radios));memset(owners,0,sizeof(owners));
    api.hw=obj;obj->hw_api=&api;obj->nof_irqs=n;obj->irq_mode=1;active=obj;required_mask=mask;
    for(unsigned i=0;i<6;i++) obj->irq_out[i]=10+i;
    external_irqs=active_steps=irq_masks=resets=pending=packet_drops=rtnl_depth=freed_owners=0;
    quiesced_owners=scan_quiesced=dfs_quiesced=0;
    fail_irq=-1;irq_enabled=1;radios.num_radios=2;
}
static void order_case(unsigned done,bool partial_mac) {
    mtlk_mmb_drv_t obj;setup(&obj,6,0x3f);active_steps=BIT(done)-1;
    if(done>STEP_MMB_RADIO_START_FINALIZE)
        for(unsigned i=0;i<2;i++) radios.radio[i].init_done=1;
    if(done>STEP_MMB_IRQ_TASKLET_INIT) assert(!init_all_tasklets(&obj));
    if(done>STEP_MMB_IRQ_START) assert(!_mmb_drv_irq_start(&obj));
    if(done>STEP_MMB_RADIO_MAC80211_INIT || partial_mac) {
        for(unsigned i=0;i<2;i++) { owners[i].allocated=1;owners[i].registered=!partial_mac;radios.radio[i].mac80211=&owners[i]; }
        pending=2;
    }
    _mmb_drv_cleanup(&obj,1);
    assert(!active_steps && !external_irqs && !obj.tasklets_initialized && !rtnl_depth && !pending);
    for(unsigned i=0;i<2;i++) assert(!owners[i].allocated);
    cases++;
}
int main(void) {
    wave_radio_mac80211_tx_quiesce(NULL);
    if(!strcmp("CASE","order")) { order_case(STEP_COUNT,false);return 0; }
    if(!strcmp("CASE","irq")) {
        mtlk_mmb_drv_t obj;setup(&obj,4,0xf);assert(!init_all_tasklets(&obj));fail_irq=1;
        assert(_mmb_drv_irq_start(&obj)==MTLK_ERR_UNKNOWN);
        printf("IRQ registration mask after request failure: %lx\n",external_irqs);fflush(stdout);
        assert(!external_irqs);return 0;
    }
    if(strcmp("CASE","irq")) {
        for(unsigned done=1;done<=STEP_COUNT;done++) order_case(done,false);
        order_case(STEP_MMB_RADIO_MAC80211_INIT,true);
    }
    unsigned counts[]={1,4,6};
    for(unsigned c=0;c<3;c++) for(unsigned mask=0;mask<(1U<<counts[c]);mask++)
      for(int fail=-1;fail<(int)counts[c];fail++) {
        mtlk_mmb_drv_t obj;setup(&obj,counts[c],mask);assert(!init_all_tasklets(&obj));fail_irq=fail;
        int should_fail=fail>=0 && (mask&BIT(fail));
        assert(_mmb_drv_irq_start(&obj)==(should_fail?MTLK_ERR_UNKNOWN:0));
        if(should_fail && external_irqs) fprintf(stderr,"failed IRQ request leaks registration mask %lx\n",external_irqs);
        assert(external_irqs==(should_fail?0:mask));
        _mmb_drv_irq_stop(&obj);_mmb_drv_irq_stop(&obj);kill_all_tasklets(&obj);kill_all_tasklets(&obj);
        assert(!external_irqs);cases++;
    }
    printf("PASS: %u IRQ acquisition/rollback and teardown-order cases (modeled synchronization)\n",cases);
}
'''.replace('\nENUM\n','\n'+enum+'\n').replace('\nFUNCTIONS\n','\n'+functions+'\n').replace('"CASE"','"'+a.case+'"')

def run(path):
    path.mkdir(parents=True,exist_ok=True);(path/'probe.c').write_text(harness)
    opts=['-static'] if a.qemu else ['-fno-pie','-no-pie','-fsanitize=address,undefined']
    subprocess.run([a.cc,'-O1','-g',*opts,str(path/'probe.c'),'-o',str(path/'probe')],check=True)
    cmd=[str(path/'probe')]
    if a.qemu:cmd.insert(0,str(a.qemu.resolve()))
    subprocess.run(cmd,check=True,cwd=path)
if a.output:run(a.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-teardown-') as tmp:run(Path(tmp))
