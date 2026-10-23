#!/usr/bin/env python3
"""Run the actual TX gate and entry wrappers against concurrent producers.

Kernel spinlocks/waitqueues use pthread equivalents; submission bodies are
fixtures. This is not concurrent kernel, IRQ, firmware or RF execution.
"""
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
hw = (a.tree / 'wireless/driver/shared/hw_mmb.c').read_text()
core = (a.tree / 'wireless/driver/linux/core.c').read_text()
drv = (a.tree / 'wireless/driver/linux/mtlk_mmb_drv.c').read_text()

def extract(text, name):
    m = re.search(r'^(?:static\s+)?(?:bool|void|int)\s+(?:__MTLK_IFUNC\s+)?' + name + r'\s*\([^;]*?\)\s*\{', text, re.M)
    assert m, name
    end, depth = m.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[m.start():end]

gate_struct = re.search(r'struct wave_tx_gate \{.*?\n\};', hw, re.S).group()
helpers = '\n'.join(extract(hw, n) for n in ['wave_hw_reset_worker', 'wave_hw_reset_request', 'wave_hw_tx_gate_init', 'wave_hw_tx_enter',
    'wave_hw_tx_exit', 'wave_hw_tx_idle', 'wave_hw_tx_drain', 'wave_hw_tx_quiesce',
    'wave_hw_tx_stop', 'wave_hw_tx_resume'])
wrappers = extract(core, '_mtlk_core_handle_tx_data') + '\n' + extract(hw, 'mtlk_mmb_bss_mgmt_tx')
# Integration assertions supplement the executable helper/wrapper tests.
restore = extract(hw, 'mtlk_hw_mmb_restore')
isolate = extract(hw, 'mtlk_hw_mmb_isolate')
cleanup = extract(drv, '_mmb_drv_cleanup')
assert restore.index('wave_hw_tx_quiesce(hw)') < restore.index('mtlk_mmb_drv_recovery_irq_quiesce(hw)') < restore.index('_mtlk_mmb_free_data_tx_buffers(hw)')
assert restore.index('hw->state = MTLK_HW_STATE_READY') < restore.index('wave_hw_tx_resume(hw)') < restore.index('restore_failed:')
assert 'wave_hw_tx_resume' not in restore[restore.index('restore_failed:'):]
assert isolate.index('wave_hw_tx_quiesce(hw)') < isolate.index('mtlk_mmb_drv_recovery_irq_quiesce(hw)')
assert cleanup.index('wave_hw_tx_stop(obj->hw_api->hw)') < cleanup.index('_mmb_drv_mac80211_deinit')
assert cleanup.index('wave_hw_tx_stop(obj->hw_api->hw)') < cleanup.index('wave_rcvry_cleanup_finalize')
reset_case = hw[hw.index('case MTLK_HW_RESET:'):].split('break;', 1)[0]
assert 'wave_hw_reset_request(hw)' in reset_case and 'wave_rcvry_task_initiate' not in reset_case
assert re.search(r'MMB_MAC_EVENTS_START, MTLK_OBJ_PTR\(obj\),\s*wave_hw_tx_resume, \(hw\)', drv)
assert hw.index('wave_hw_tx_gate_init(hw);') < hw.index('hw_api->hw = hw;', hw.index('mtlk_hw_mmb_add_card (void)'))

harness = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sched.h>
typedef pthread_mutex_t spinlock_t;
typedef struct { pthread_mutex_t lock; pthread_cond_t cond; unsigned seq; } wait_queue_head_t;
#define spin_lock_init(p) assert(!pthread_mutex_init(p,NULL))
#define spin_lock_irqsave(p,f) do { (f)=0;assert(!pthread_mutex_lock(p)); } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(f);assert(!pthread_mutex_unlock(p)); } while(0)
#define WARN_ON_ONCE(x) (assert(!(x)),false)
#define __MTLK_IFUNC
static void init_waitqueue_head(wait_queue_head_t *w) {
    assert(!pthread_mutex_init(&w->lock,NULL));assert(!pthread_cond_init(&w->cond,NULL));w->seq=0;
}
static void wake_up_all(wait_queue_head_t *w) {
    assert(!pthread_mutex_lock(&w->lock));w->seq++;assert(!pthread_cond_broadcast(&w->cond));assert(!pthread_mutex_unlock(&w->lock));
}
/* Snapshot the wake generation before checking the predicate. Never hold
 * the waitqueue mutex while acquiring the gate lock: the kernel likewise
 * releases its waitqueue lock before evaluating wait_event's condition. */
#define wait_event(w,condition) do { for(;;) { \
    assert(!pthread_mutex_lock(&(w).lock));unsigned seq=(w).seq;assert(!pthread_mutex_unlock(&(w).lock)); \
    if(condition)break; \
    assert(!pthread_mutex_lock(&(w).lock)); \
    while(seq==(w).seq)assert(!pthread_cond_wait(&(w).cond,&(w).lock)); \
    assert(!pthread_mutex_unlock(&(w).lock)); \
} } while(0)
/* Explicitly dispatched workqueue model: schedule never runs the callback
 * inline. A running callback may have one pending follow-up, as in Linux. */
struct work_struct {
    pthread_mutex_t lock; pthread_cond_t cond;
    void (*fn)(struct work_struct *); bool pending,running;
};
static void init_work(struct work_struct *w,void (*fn)(struct work_struct *)) {
    assert(!pthread_mutex_init(&w->lock,NULL));assert(!pthread_cond_init(&w->cond,NULL));
    w->fn=fn;w->pending=w->running=false;
}
#define INIT_WORK(w,fn) init_work(w,fn)
static bool schedule_work(struct work_struct *w) {
    assert(!pthread_mutex_lock(&w->lock));bool fresh=!w->pending;w->pending=true;
    assert(!pthread_mutex_unlock(&w->lock));return fresh;
}
static void cancel_work_sync(struct work_struct *w) {
    assert(!pthread_mutex_lock(&w->lock));w->pending=false;
    while(w->running)assert(!pthread_cond_wait(&w->cond,&w->lock));
    assert(!pthread_mutex_unlock(&w->lock));
}
static void *dispatch_work(void *arg) {
    struct work_struct *w=arg;
    assert(!pthread_mutex_lock(&w->lock));assert(w->pending && !w->running);
    w->pending=false;w->running=true;assert(!pthread_mutex_unlock(&w->lock));
    w->fn(w);
    assert(!pthread_mutex_lock(&w->lock));w->running=false;
    assert(!pthread_cond_broadcast(&w->cond));assert(!pthread_mutex_unlock(&w->lock));return NULL;
}
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define READ_ONCE(x) (x)
GATE_STRUCT
typedef struct { struct wave_tx_gate tx_gate; struct work_struct reset_work; int state; } mtlk_hw_t;
typedef mtlk_hw_t *mtlk_vap_handle_t;
typedef struct { mtlk_vap_handle_t vap_handle; } mtlk_core_t;
typedef struct { unsigned marker; } mtlk_core_handle_tx_data_t;
typedef struct { unsigned marker,accepted; } mtlk_nbuf_t;
typedef uint32_t uint32;
typedef uint64_t uint64;
typedef uint8_t uint8;
typedef int BOOL;
#define MTLK_ERR_PKT_DROPPED -11
#define MTLK_ERR_NOT_READY -12
#define MTLK_ERR_OK 0
static bool mtlk_hw_is_halted(int state) { return state==1; }
static void wave_rcvry_task_initiate(mtlk_hw_t *hw);
static void _mtlk_mmb_handle_sw_trap(mtlk_hw_t *hw);
static mtlk_hw_t *mtlk_vap_get_hw(mtlk_vap_handle_t v) { assert(v);return v; }
HELPERS
struct producer { mtlk_hw_t *hw; unsigned kind; int result; bool entered,released; };
static _Thread_local struct producer *self;
static pthread_mutex_t control=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static atomic_uint bodies;
static atomic_bool drained;
static int immediate_result;
static bool permanently;
static atomic_uint resets,traps;
static atomic_bool reset_hold,reset_entered,reset_release;
static void wave_rcvry_task_initiate(mtlk_hw_t *hw) {
    atomic_fetch_add(&resets,1);
    wave_hw_tx_quiesce(hw);
    atomic_store(&reset_entered,true);
    while(atomic_load(&reset_hold) && !atomic_load(&reset_release))sched_yield();
}
static void _mtlk_mmb_handle_sw_trap(mtlk_hw_t *hw) { (void)hw;atomic_fetch_add(&traps,1); }
static void destroy_hw(mtlk_hw_t *hw) {
    assert(!hw->reset_work.pending && !hw->reset_work.running);
    assert(!pthread_cond_destroy(&hw->reset_work.cond));assert(!pthread_mutex_destroy(&hw->reset_work.lock));
    assert(!pthread_cond_destroy(&hw->tx_gate.wait.cond));assert(!pthread_mutex_destroy(&hw->tx_gate.wait.lock));assert(!pthread_mutex_destroy(&hw->tx_gate.lock));
}
static int submission_body(mtlk_hw_t *hw) {
    unsigned long flags;
    spin_lock_irqsave(&hw->tx_gate.lock,flags);assert(hw->tx_gate.users);spin_unlock_irqrestore(&hw->tx_gate.lock,flags);
    atomic_fetch_add(&bodies,1);
    if(!self)return immediate_result;
    assert(!pthread_mutex_lock(&control));self->entered=true;assert(!pthread_cond_broadcast(&changed));
    while(!self->released)assert(!pthread_cond_wait(&changed,&control));
    assert(!pthread_mutex_unlock(&control));return self->result;
}
static int _mtlk_core_handle_tx_data_impl(mtlk_core_t *nic,mtlk_core_handle_tx_data_t *data,uint32 flags) {
    assert(data->marker==123 && flags==17);return submission_body(nic->vap_handle);
}
static int _mtlk_mmb_bss_mgmt_tx_submit(mtlk_vap_handle_t vap,const uint8 *buf,size_t len,int channum,
    BOOL no_cck,BOOL no_ack,BOOL broadcast,uint64 *cookie,uint32 processing,mtlk_nbuf_t *skb,BOOL pm,uint32 tid) {
    assert(buf && buf[0]==42 && len==24 && channum==36 && no_cck==1 && no_ack==0 && broadcast==1);
    assert(cookie && *cookie==0 && processing==2 && skb && skb->marker==234 && pm==0 && tid==3);
    int res=submission_body(vap);if(!res){*cookie=99;skb->accepted=1;}return res;
}
WRAPPERS
static int call_wrapper(mtlk_hw_t *hw,unsigned kind) {
    if(!kind) {
        mtlk_core_t nic={.vap_handle=hw};mtlk_core_handle_tx_data_t data={.marker=123};
        return _mtlk_core_handle_tx_data(&nic,&data,17);
    }
    uint8 buf[24]={42};uint64 cookie=0;mtlk_nbuf_t skb={.marker=234};
    int res=mtlk_mmb_bss_mgmt_tx(hw,buf,sizeof(buf),36,1,0,1,&cookie,2,&skb,0,3);
    assert(cookie==(!res?99:0) && skb.accepted==!res);return res;
}
static void *producer_thread(void *arg) {
    self=arg;assert(call_wrapper(self->hw,self->kind)==self->result);return NULL;
}
static void *drain_thread(void *arg) {
    mtlk_hw_t *hw=arg;
    if(permanently)wave_hw_tx_stop(hw);else wave_hw_tx_quiesce(hw);
    assert(wave_hw_tx_idle(hw));atomic_store(&drained,true);return NULL;
}
static bool accepting(mtlk_hw_t *hw) {
    unsigned long flags;bool open;
    spin_lock_irqsave(&hw->tx_gate.lock,flags);open=hw->tx_gate.accepting;spin_unlock_irqrestore(&hw->tx_gate.lock,flags);return open;
}
static void rejected(mtlk_hw_t *hw) {
    unsigned old=atomic_load(&bodies);
    assert(call_wrapper(hw,0)==MTLK_ERR_PKT_DROPPED);
    assert(call_wrapper(hw,1)==MTLK_ERR_NOT_READY);
    assert(atomic_load(&bodies)==old);
}
static void scenario(unsigned count,unsigned stop,unsigned error,unsigned first_kind) {
    mtlk_hw_t hw;struct producer p[8]={0};pthread_t threads[8],drainer;
    memset(&hw,0,sizeof(hw));wave_hw_tx_gate_init(&hw);atomic_store(&bodies,0);atomic_store(&drained,false);
    permanently=stop;immediate_result=error?-7:0;rejected(&hw);
    wave_hw_tx_resume(&hw);wave_hw_tx_resume(&hw);
    for(unsigned i=0;i<count;i++) {
        p[i].hw=&hw;p[i].kind=(i+first_kind)%2;p[i].result=immediate_result;
        assert(!pthread_create(&threads[i],NULL,producer_thread,&p[i]));
    }
    assert(!pthread_mutex_lock(&control));
    for(unsigned i=0;i<count;i++)while(!p[i].entered)assert(!pthread_cond_wait(&changed,&control));
    assert(!pthread_mutex_unlock(&control));
    assert(!pthread_create(&drainer,NULL,drain_thread,&hw));
    while(accepting(&hw))sched_yield();
    if(count)assert(!atomic_load(&drained));
    rejected(&hw);
    if(stop){wave_hw_tx_resume(&hw);rejected(&hw);}
    for(unsigned i=0;i<count;i++) {
        assert(!pthread_mutex_lock(&control));p[i].released=true;assert(!pthread_cond_broadcast(&changed));assert(!pthread_mutex_unlock(&control));
        assert(!pthread_join(threads[i],NULL));
        if(i+1<count)assert(!atomic_load(&drained));
    }
    assert(!pthread_join(drainer,NULL));assert(atomic_load(&drained));assert(wave_hw_tx_idle(&hw));
    assert(atomic_load(&bodies)==count);
    wave_hw_tx_quiesce(&hw);rejected(&hw);wave_hw_tx_resume(&hw);
    if(stop)rejected(&hw);
    else {
        assert(call_wrapper(&hw,0)==immediate_result && call_wrapper(&hw,1)==immediate_result);
        assert(wave_hw_tx_idle(&hw));wave_hw_tx_quiesce(&hw);rejected(&hw);
    }
    wave_hw_tx_stop(&hw);wave_hw_tx_resume(&hw);wave_hw_tx_resume(&hw);rejected(&hw);
    destroy_hw(&hw);
}
static void reset_scenarios(void) {
    mtlk_hw_t hw={0};pthread_t worker,stopper;
    wave_hw_tx_gate_init(&hw);wave_hw_tx_resume(&hw);
    assert(wave_hw_tx_enter(&hw));
    assert(wave_hw_reset_request(&hw)==MTLK_ERR_OK);
    assert(wave_hw_reset_request(&hw)==MTLK_ERR_OK); /* coalesced pending */
    assert(!atomic_load(&resets) && !atomic_load(&traps));
    assert(!pthread_create(&worker,NULL,dispatch_work,&hw.reset_work));
    while(accepting(&hw))sched_yield();
    assert(!atomic_load(&reset_entered) && !atomic_load(&traps));
    wave_hw_tx_exit(&hw);
    assert(!pthread_join(worker,NULL));
    assert(atomic_load(&resets)==1 && atomic_load(&traps)==1);
    wave_hw_tx_resume(&hw);
    hw.state=1;assert(wave_hw_reset_request(&hw)==MTLK_ERR_NOT_READY);hw.state=0;
    assert(wave_hw_reset_request(&hw)==MTLK_ERR_OK);
    /* Halt between acceptance and dispatch is checked by the worker too. */
    hw.state=1;dispatch_work(&hw.reset_work);hw.state=0;
    assert(atomic_load(&resets)==1 && atomic_load(&traps)==1);
    assert(wave_hw_reset_request(&hw)==MTLK_ERR_OK);
    wave_hw_tx_stop(&hw);assert(!hw.reset_work.pending);
    assert(wave_hw_reset_request(&hw)==MTLK_ERR_NOT_READY);destroy_hw(&hw);

    memset(&hw,0,sizeof(hw));wave_hw_tx_gate_init(&hw);wave_hw_tx_resume(&hw);
    atomic_store(&reset_hold,true);atomic_store(&reset_entered,false);atomic_store(&reset_release,false);
    assert(wave_hw_reset_request(&hw)==MTLK_ERR_OK);
    assert(!pthread_create(&worker,NULL,dispatch_work,&hw.reset_work));
    while(!atomic_load(&reset_entered))sched_yield();
    /* Queue a follow-up while running, then ensure stop cancels it and waits. */
    assert(wave_hw_reset_request(&hw)==MTLK_ERR_OK);
    permanently=true;atomic_store(&drained,false);
    assert(!pthread_create(&stopper,NULL,drain_thread,&hw));
    for(;;) {
        unsigned long flags;bool stopping;
        spin_lock_irqsave(&hw.tx_gate.lock,flags);stopping=hw.tx_gate.stopping;spin_unlock_irqrestore(&hw.tx_gate.lock,flags);
        if(stopping)break;sched_yield();
    }
    assert(!atomic_load(&drained));assert(wave_hw_reset_request(&hw)==MTLK_ERR_NOT_READY);
    atomic_store(&reset_release,true);
    assert(!pthread_join(worker,NULL));assert(!pthread_join(stopper,NULL));
    assert(atomic_load(&resets)==2 && atomic_load(&traps)==2);
    wave_hw_tx_resume(&hw);rejected(&hw);destroy_hw(&hw);
    puts("PASS: deferred reset, coalescing, halted requests/dispatch, pending cancellation and running-worker drain (workqueue model)");
}
int main(void) {
    alarm(60);unsigned cases=0;
    for(unsigned count=0;count<=8;count++)for(unsigned stop=0;stop<2;stop++)for(unsigned error=0;error<2;error++)for(unsigned kind=0;kind<2;kind++) {
        scenario(count,stop,error,kind);cases++;
    }
    printf("PASS: %u concurrent TX-gate/wrapper scenarios (pthread lock/waitqueue model; no kernel/firmware execution)\n",cases);
    reset_scenarios();
}
'''
for key, value in [('GATE_STRUCT', gate_struct), ('HELPERS', helpers), ('WRAPPERS', wrappers)]:
    harness = harness.replace('\n' + key + '\n', '\n' + value + '\n')

def run(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'probe.c').write_text(harness)
    flags = ['-static'] if a.qemu else ['-fno-pie', '-no-pie', '-fsanitize=address,undefined']
    subprocess.run([a.cc, '-std=gnu11', '-O1', '-g', '-pthread', *flags,
                    str(path / 'probe.c'), '-o', str(path / 'probe')], check=True)
    command = [str(path / 'probe')]
    if a.qemu:
        command.insert(0, str(a.qemu.resolve()))
    subprocess.run(command, check=True, cwd=path)

if a.output:
    run(a.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-tx-gate-') as tmp:
        run(Path(tmp))
