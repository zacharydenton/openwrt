#!/usr/bin/env python3
"""Execute recovery IRQ helpers and the complete HW restore control flow.

Kernel IRQ/tasklet synchronization and firmware/resource operations are modeled.
This does not run a kernel interrupt engine, producer threads or firmware.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tree', type=Path)
p.add_argument('--before', type=Path)
p.add_argument('--cc', default='gcc')
p.add_argument('--qemu', type=Path)
p.add_argument('--output', type=Path)
a = p.parse_args()
drv = (a.tree / 'wireless/driver/linux/mtlk_mmb_drv.c').read_text()
current = (a.tree / 'wireless/driver/shared/hw_mmb.c').read_text()
source = a.before.read_text() if a.before else current

def extract(text, name):
    m = re.search(r'^(?:static\s+)?(?:void|int)\s+(?:__MTLK_IFUNC\s+)?' + name + r'\s*\([^;]*?\)\s*\{', text, re.M)
    assert m, name
    end, depth = m.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[m.start():end]

restore = extract(source, 'mtlk_hw_mmb_restore')
current_restore = extract(current, 'mtlk_hw_mmb_restore')
fallible = sorted(set(re.findall(r'res = (\w+)\(', current_restore)))
resources = ['_mtlk_mmb_prepare_man_req_bdr', '_mtlk_mmb_prepare_man_ind_bdr',
             '_mtlk_mmb_prepare_dbg_req_bdr', '_mtlk_mmb_prepare_dbg_ind_bdr',
             '_mtlk_mmb_recover_data_req_bdr', '_mtlk_mmb_recover_data_ind_bdr',
             '_mtlk_mmb_recover_bss_mgmt', '_mtlk_mmb_prealloc_rx_data_buffers',
             '_mtlk_mmb_prealloc_rx_mgmt_buffers', '_mtlk_mmb_txmm_restore',
             '_mtlk_mmb_txdm_restore']
calls = sorted(set(re.findall(r'\b((?:_mtlk_mmb_|__hw_mmb_|mtlk_hw_mmb_|mtlk_ccr_|mtlk_osal_timer_)\w+)\(', current_restore)))
actual = ['mtlk_hw_mmb_restore', 'mtlk_hw_mmb_reset_mac']
functions = '\n'.join(extract(drv, n) for n in ['_mmb_drv_drain_tasklets',
    'mtlk_mmb_drv_recovery_irq_quiesce', 'mtlk_mmb_drv_recovery_irq_resume', '_mmb_drv_irq_stop'])
functions += '\n' + '\n'.join(extract(source, n) for n in ['_mtlk_mmb_stop_events_completely', '_mtlk_mmb_reset_all_events'])
actual += ['_mtlk_mmb_stop_events_completely', '_mtlk_mmb_reset_all_events']
stubs = '\n'.join('#define ' + n + '(...) stage("' + n + '")' for n in calls if n not in actual)
isolate = extract(current, 'mtlk_hw_mmb_isolate')
assert isolate.index('_mtlk_mmb_stop_events_completely(hw)') < isolate.index('mtlk_mmb_drv_recovery_irq_quiesce(hw)') < isolate.index('mtlk_osal_timer_cancel_sync(')

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define __MTLK_IFUNC
#define MTLK_ERR_OK 0
#define MTLK_ASSERT(x) assert(x)
#define MTLK_IRQ_NONE 0
#define MTLK_HW_STATE_WAITING_READY 1
#define MTLK_HW_STATE_READY 2
#define TRUE 1
#define LOGGER_SEVERITY_DEFAULT_LEVEL 0
#define UMI_CPU_ID_UM 0
#define MTLK_RX_BUFFS_RECOVERY_PERIOD 10000
#define ELOG_D(...) ((void)0)
#define ELOG_V(...) ((void)0)
#define ILOG2_V(...) ((void)0)
#define LOG_CHI_AREA(...) ((void)0)
#define LOG_CHI_RING(...) ((void)0)
#define LOG_CHI_POOL(...) ((void)0)
#define BIT(i) (1UL<<(i))
#define container_of(p,type,member) ((type *)((char *)(p)-offsetof(type,member)))
#define WRITE_ONCE(x,v) ((x)=(v))
#define smp_store_release(p,v) __atomic_store_n(p,v,__ATOMIC_RELEASE)
#define smp_load_acquire(p) __atomic_load_n(p,__ATOMIC_ACQUIRE)
typedef unsigned uint32;
typedef uint16_t uint16;
typedef struct { int marker; } mtlk_ccr_t;
typedef struct { unsigned pending; } tasklet;
typedef struct { unsigned irq_no,status; } irq_data;
typedef struct { unsigned offset,size,idx; } bd;
typedef struct _mtlk_hw_t {
    mtlk_ccr_t *ccr;void *radio_descr;
    int mac_events_stopped,mac_events_stopped_completely;
    void (*perform_isr_action)(void);
    struct { struct { struct { unsigned u32IndStartOffset,u32IndNumOfElements,u32ReqStartOffset,u32ReqNumOfElements; } sFifoQ; } sBasic;
      struct { struct { unsigned u32DescriptorLocation; } sData; } sMipsControl; } chi_area;
    struct { bd ind,req; } bds;
    struct { struct { int timer; } pending; } rx;
    int fw_log_is_supported,mac_reset_logic_initialized,state;
} mtlk_hw_t;
typedef struct { mtlk_hw_t *hw; } hw_api;
typedef struct { mtlk_ccr_t ccr;hw_api *hw_api;int nof_irqs,irq_out[6];
    irq_data irq_handler_data[6];tasklet irq_tasklet[6],irq_tasklets_global[1];
    irq_data *ihd_pending;unsigned long requested_irqs,recovery_disabled_irqs;
    bool tasklets_initialized;
} mtlk_mmb_drv_t;
static mtlk_hw_t hw;
static hw_api api;
static mtlk_mmb_drv_t obj;
static unsigned long linux_disabled,registered,resource_bits;
static unsigned disables,enables,kills,fallible_calls,fail_at,stages,resets;
static bool hw_masked,dcdp,callback_seen,producer_open;
static void isr_action_init(void) {}
static void isr_action_normal(void) {}
static void *mtlk_hw_mmb_get_ccr(mtlk_hw_t *h) { return h->ccr; }
static int _mmb_drv_is_irqno_required(mtlk_hw_t *h,unsigned bit) { (void)h;return !!(registered & BIT(bit)); }
static void mtlk_hw_mmb_dis_interrupts(mtlk_hw_t *h) { assert(h==&hw);hw_masked=true; }
static void disable_irq(int irq) {
    unsigned i=irq-10;assert(registered&BIT(i));assert(!(linux_disabled&BIT(i)));
    linux_disabled|=BIT(i);disables++;
}
static void enable_irq(int irq) {
    unsigned i=irq-10;assert(linux_disabled&BIT(i));linux_disabled&=~BIT(i);enables++;
}
static void free_irq(int irq,void *data) {
    unsigned i=irq-10;(void)data;assert(registered&BIT(i));assert(!(linux_disabled&BIT(i)));registered&=~BIT(i);
}
static void tasklet_kill(tasklet *t) {
    assert(linux_disabled==registered);
    /* Model an already-running tasklet re-enabling its hardware source.
     * Linux delivery must stay disabled until every tasklet is drained. */
    if(t->pending)hw_masked=false;
    t->pending=0;kills++;
}
static void assert_drained(void) {
    assert(linux_disabled==registered && hw_masked);
    for(unsigned i=0;i<6;i++)assert(!obj.irq_tasklet[i].pending);
    assert(!obj.irq_tasklets_global[0].pending);
}
static void wave_hw_tx_quiesce(mtlk_hw_t *h) { assert(h==&hw);producer_open=false; }
static void wave_hw_tx_resume(mtlk_hw_t *h) {
    assert(h==&hw && hw.state==MTLK_HW_STATE_READY && resource_bits==((1UL<<11)-1));producer_open=true;
}
static void mtlk_hw_mmb_reset_mac(mtlk_hw_t *h) {
    assert(h==&hw && !producer_open);
    if(!hw.mac_events_stopped || !hw.mac_events_stopped_completely || linux_disabled!=registered)
        fprintf(stderr,"restore resets old firmware before event closure/IRQ drain\n");
    assert(hw.mac_events_stopped && hw.mac_events_stopped_completely);assert_drained();
    resource_bits=0;resets++;
}
static int mtlk_mmb_dcdp_path_available(mtlk_hw_t *h) { assert(h==&hw);return dcdp; }
static const char *fallible_names[]={FALLIBLE};
static const char *resource_names[]={RESOURCES};
static int stage(const char *name) {
    stages++;
    if(hw.perform_isr_action==isr_action_normal && !hw.mac_events_stopped_completely) {
        assert(resource_bits==((1UL<<11)-1));callback_seen=true;
    }
    if(!strcmp(name,"_mtlk_mmb_run_firmware")) {
        assert(!linux_disabled && hw.perform_isr_action==isr_action_init);
        assert(hw.mac_events_stopped && hw.mac_events_stopped_completely);
    }
    if(!strcmp(name,"_mtlk_mmb_power_on")) {
        assert_drained();assert(hw.mac_events_stopped && hw.mac_events_stopped_completely);
    }
    if(!strcmp(name,"_mtlk_mmb_send_hw_dep_cfg") || !strcmp(name,"_mtlk_mmb_send_fw_log_severity"))
        assert(!linux_disabled && !hw.mac_events_stopped_completely && hw.perform_isr_action==isr_action_normal);
    for(unsigned i=0;i<sizeof(fallible_names)/sizeof(fallible_names[0]);i++)if(!strcmp(name,fallible_names[i])) {
        if(++fallible_calls==fail_at)return -17;
    }
    for(unsigned i=0;i<11;i++)if(!strcmp(name,resource_names[i]))resource_bits|=BIT(i);
    return 0;
}
STUBS
FUNCTIONS
RESTORE
static void setup(unsigned n,unsigned mask,bool global) {
    memset(&hw,0,sizeof(hw));memset(&obj,0,sizeof(obj));api.hw=&hw;obj.hw_api=&api;
    obj.nof_irqs=n;obj.requested_irqs=registered=mask;obj.tasklets_initialized=true;
    hw.ccr=&obj.ccr;hw.radio_descr=&obj;hw.mac_events_stopped=hw.mac_events_stopped_completely=1;
    hw.perform_isr_action=isr_action_normal;
    for(unsigned i=0;i<n;i++) {
        obj.irq_out[i]=10+i;obj.irq_handler_data[i].irq_no=i;obj.irq_handler_data[i].status=0xff;
        obj.irq_tasklet[i].pending=!!(mask&BIT(i));
    }
    if(global){obj.ihd_pending=&obj.irq_handler_data[0];obj.irq_tasklets_global[0].pending=1;}
    linux_disabled=disables=enables=kills=fallible_calls=fail_at=stages=resets=resource_bits=0;
    hw_masked=dcdp=callback_seen=false;producer_open=true;
}
int main(void) {
    unsigned irq_cases=0,restore_cases=0,counts[]={1,4,6};
    if(BEFORE) {
        setup(6,63,true);(void)mtlk_hw_mmb_restore(&hw);return 0;
    }
    for(unsigned nidx=0;nidx<3;nidx++)for(unsigned mask=0;mask<(1U<<counts[nidx]);mask++)for(unsigned global=0;global<2;global++) {
        setup(counts[nidx],mask,global);
        mtlk_mmb_drv_recovery_irq_quiesce(&hw);assert_drained();unsigned saved=disables;
        mtlk_mmb_drv_recovery_irq_quiesce(&hw);assert_drained();assert(disables==saved && obj.tasklets_initialized);
        mtlk_mmb_drv_recovery_irq_resume(&hw);assert(!linux_disabled && enables==saved);
        mtlk_mmb_drv_recovery_irq_resume(&hw);assert(enables==saved);
        mtlk_mmb_drv_recovery_irq_quiesce(&hw);assert_drained();
        _mmb_drv_irq_stop(&obj);assert(!linux_disabled && !registered && !obj.requested_irqs && disables==enables);
        _mmb_drv_irq_stop(&obj);irq_cases++;
    }
    for(unsigned path=0;path<2;path++)for(unsigned logger=0;logger<2;logger++)for(unsigned ctrl=0;ctrl<2;ctrl++) {
        unsigned total=0;
        for(unsigned failure=0;failure<=total;failure++) {
            setup(6,63,true);dcdp=path;hw.fw_log_is_supported=logger;hw.chi_area.sMipsControl.sData.u32DescriptorLocation=ctrl;fail_at=failure;
            int res=mtlk_hw_mmb_restore(&hw);
            if(!failure) { assert(!res && callback_seen && producer_open);total=fallible_calls;assert(!linux_disabled && !hw.mac_events_stopped && !hw.mac_events_stopped_completely); }
            else {
                assert(res==-17 && fallible_calls==failure && !producer_open);assert_drained();
                assert(hw.mac_events_stopped && hw.mac_events_stopped_completely);
                /* A subsequent attempt must not accumulate Linux disable depth. */
                fail_at=fallible_calls=0;assert(!mtlk_hw_mmb_restore(&hw));assert(!linux_disabled && disables==enables);
            }
            _mmb_drv_irq_stop(&obj);assert(!registered && !linux_disabled);restore_cases++;
        }
    }
    printf("PASS: %u IRQ lifecycle and %u full-restore/failure-retry cases (DCDP_SEPARATE_REG=%d; modeled synchronization/resources)\n",irq_cases,restore_cases,MTLK_DCDP_SEPARATE_REG);
}
'''
for key, value in [('FALLIBLE', ','.join('"' + n + '"' for n in fallible)),
                   ('RESOURCES', ','.join('"' + n + '"' for n in resources)),
                   ('STUBS', stubs), ('FUNCTIONS', functions), ('RESTORE', restore),
                   ('BEFORE', str(int(bool(a.before))))]:
    harness = harness.replace(key, value)

def run(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'probe.c').write_text(harness)
    for separate in [0, 1]:
        binary = path / ('probe-' + str(separate))
        flags = ['-static'] if a.qemu else ['-fno-pie', '-no-pie', '-fsanitize=address,undefined']
        subprocess.run([a.cc, '-std=gnu11', '-O1', '-g', *flags,
                        '-DMTLK_DCDP_SEPARATE_REG=' + str(separate), str(path / 'probe.c'), '-o', str(binary)], check=True)
        command = [str(binary)]
        if a.qemu:
            command.insert(0, str(a.qemu.resolve()))
        subprocess.run(command, check=True, cwd=path)

if a.output:
    run(a.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-recovery-irq-') as tmp:
        run(Path(tmp))
