#!/usr/bin/env python3
"""Compile the real UMT state functions with deterministic MMIO/CBM stubs."""
import pathlib, subprocess, tempfile, sys
if len(sys.argv) > 1:
    source = pathlib.Path(sys.argv[1]).read_text()
else:
    patch = (pathlib.Path(__file__).resolve().parents[1] / '170-grx500-directconnect.patch').read_text()
    added = patch.split('+++ b/drivers/dma/grx500-umt.c\n',1)[1]
    source = '\n'.join(line[1:] for line in added.splitlines() if line.startswith('+'))
names = ['umt_tick', 'umt_reg', 'umt_mask', 'umt_hw_enable', 'ltq_umt_request', 'ltq_umt_set_mode',
         'ltq_umt_enable', 'ltq_umt_set_period', 'ltq_umt_suspend', 'ltq_umt_release',
         'umt_reset_port_dq_idx']
import re
parts=[]
for name in names:
    match=re.search(r'^(?:static )?(?:u32|void|int|enum hrtimer_restart) '+name+r'\(', source, re.M)
    assert match, name
    start=source.index('{', match.start()); depth=1; end=start+1
    while depth:
        depth += (source[end]=='{')-(source[end]=='}'); end+=1
    parts.append(source[match.start():end])
stubs=r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stddef.h>
typedef uint32_t u32; typedef uint64_t u64;
#define __iomem
#define UMT_PORTS 4
#define UMT_TICK_US 40
#define GCTRL 0x200
#define TRG_MUX 0xe0
#define CNT_CTRL 0xe4
#define BIT(n) (1U<<(n))
#define max(a,b) ((a)>(b)?(a):(b))
#define spin_lock_irqsave(lock, flags) ((void)(lock), (flags)=0)
#define spin_unlock_irqrestore(lock,flags) ((void)(flags))
static void kfree(void *p) { free(p); }
#define DMA1TX 1
#define UMT_DISABLE 0
#define UMT_ENABLE 1
#define UMT_MODE_MAX 2
#define UMT_STATUS_MAX 2
#define UMT_MSG_MAX 4
#define UMT_MSG1_ONLY 2
#define UMT_MSG0_ONLY 1
enum umt_msg_mode { MSG0=1,MSG1=2,BOTH=3 };
struct umt_set_mode { u32 umt_mode,msg_mode,enable,phy_dst,umt_ep_dst,period,msg1_period; };
struct grx500_umt_port { u32 ep,cbm,dma,dq,dq_idx,dst,msgmode,period,msg1_period;
 void *notify; u64 next_ns; bool enabled,suspended; };
enum hrtimer_restart { HRTIMER_NORESTART, HRTIMER_RESTART };
struct hrtimer { int dummy; };
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define NSEC_PER_USEC 1000
#define min(a,b) ((a)<(b)?(a):(b))
#define ns_to_ktime(v) (v)
static u64 clock_now;
static u64 ktime_get_ns(void) { return clock_now; }
static void hrtimer_forward_now(struct hrtimer *t,u64 d) {}
static u32 dequeue_count;
static int cbm_dequeue_dma_port_stats_get(u32 port,u32 *count,u32 flags) { *count=dequeue_count; return 0; }
struct grx500_umt { struct hrtimer timer; void *base; u32 ticks_per_us; struct grx500_umt_port ports[4]; };
static int umt_lock, starts;
static struct grx500_umt *umt;
static void umt_start_timer(struct grx500_umt *u) { starts++; }
static u32 readl(void *a) { return *(u32*)a; }
static void writel(u32 v,void *a) { *(u32*)a=v; }
struct dq_info { u32 port_no; };
typedef struct { struct dq_info *deq_info; u32 num_deq_ports; } cbm_dq_port_res_t;
static int cbm_dequeue_port_resources_get(u32 ep,cbm_dq_port_res_t *r,u32 flags) {
 r->deq_info=calloc(1,sizeof(*r->deq_info)); r->num_deq_ports=1;
 r->deq_info->port_no=ep==1?4:22+ep; return 0; }
'''
checks=r'''
int main(void) {
 uint32_t registers[512]={0}; struct grx500_umt hw={.base=registers,.ticks_per_us=303};
 u32 ctrl,ch,id, i; struct umt_set_mode mode={0,3,1,0x12340000,0x56780000,200,40};
 for(i=0;i<4;i++) hw.ports[i].dma=7+i;
 assert(ltq_umt_request(1,0,&ctrl,&ch,&id)==-ENODEV); umt=&hw;
 assert(ltq_umt_request(0,0,&ctrl,&ch,&id)==-EINVAL);
 for(i=0;i<4;i++) { assert(!ltq_umt_request(i+1,i,&ctrl,&ch,&id)); assert(id==i && ch==7+i && ctrl==1); }
 assert(!ltq_umt_request(3,2,&ctrl,&ch,&id) && id==2);
 assert(ltq_umt_request(1,3,&ctrl,&ch,&id)==-ENOSPC);
 assert(readl(hw.base+TRG_MUX)==0x3210a987);
 for(i=0;i<4;i++) {
  assert(!ltq_umt_set_mode(i,i+1,&mode));
  assert(readl(hw.base+umt_reg(i,0x230,0x30))==mode.phy_dst);
  assert(readl(hw.base+umt_reg(i,0xdc,0x20))==60600);
  assert(hw.ports[i].enabled);
 }
 assert(starts==4);
 assert(ltq_umt_enable(1,1,0)==-EINVAL);
 assert(!ltq_umt_suspend(1,2,1) && hw.ports[1].suspended && (readl(hw.base+CNT_CTRL)&BIT(1)));
 assert(!ltq_umt_suspend(1,2,0) && !hw.ports[1].suspended);
 assert(!ltq_umt_set_period(2,3,MSG1,20) && hw.ports[2].msg1_period==40);
 assert(readl(hw.base+umt_reg(2,0xdc,0x20))==60600);
 assert(!ltq_umt_set_period(2,3,MSG0,50) && readl(hw.base+umt_reg(2,0xdc,0x20))==15150);
 assert(ltq_umt_set_period(2,3,MSG0,0)==-EINVAL);
 hw.ports[2].dq_idx=99; umt_reset_port_dq_idx(25); assert(!hw.ports[2].dq_idx);
 assert(!ltq_umt_release(2,3) && !hw.ports[2].enabled && !hw.ports[2].ep && hw.ports[2].dma==9);
 assert(!ltq_umt_request(3,2,&ctrl,&ch,&id) && id==2 && ch==9);
 for(i=0;i<4;i++) hw.ports[i].enabled=false;
 hw.ports[0].enabled=true; hw.ports[0].notify=registers; hw.ports[0].dq_idx=0xfffffff0U;
 hw.ports[0].next_ns=0; hw.ports[0].msg1_period=40; hw.ports[0].msgmode=3;
 dequeue_count=0x30; clock_now=1000000;
 assert(umt_tick(&hw.timer)==HRTIMER_RESTART && registers[1]==32 && hw.ports[0].dq_idx==0x10);
 registers[1]=0; assert(umt_tick(&hw.timer)==HRTIMER_RESTART && registers[1]==0);
 clock_now+=40000; assert(umt_tick(&hw.timer)==HRTIMER_RESTART && registers[1]==32 && hw.ports[0].dq_idx==0x30);
 hw.ports[0].suspended=true; assert(umt_tick(&hw.timer)==HRTIMER_NORESTART);
 puts("PASS: actual UMT counter wrap/cap/scheduling, allocation, register fields, enable/suspend, periods, reset/reuse");
}
'''
with tempfile.TemporaryDirectory() as d:
    p=pathlib.Path(d); (p/'test.c').write_text(stubs+'\n'.join(parts)+checks)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wno-unused-parameter',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
