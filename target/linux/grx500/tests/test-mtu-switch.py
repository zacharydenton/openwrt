#!/usr/bin/env python3
"""Run actual Ethernet MTU/register helpers with a fault-injected switch API.

This models register contents and API errors, not switch packet processing.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, default=root / 'files/drivers/net/ethernet/lantiq/ltq_eth_drv_xrx500.c')
p.add_argument('--case', choices=('all', 'threshold', 'failure'), default='all')
p.add_argument('--cc', default='gcc')
p.add_argument('--qemu', type=Path)
p.add_argument('--output', type=Path)
a = p.parse_args()
source = a.source.read_text()
start = re.search(r'^(?:static )?(?:int|void) gsw_reg_set_bit\(', source, re.M).start()
code = source[start:source.index('static int ltq_start_xmit(', start)]
constants = '\n'.join(re.findall(r'^#define GRX500_PMAC_JUMBO_LEN .*$', source, re.M))
headers = (root / 'files/include/net/switch_api/lantiq_gsw_flow.h').read_text()
register_type = re.search(r'typedef struct \{[^}]*\} GSW_register_t;', headers, re.S).group(0)
harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint16_t u16;
#define ETH_DATA_LEN 1500
#define ETH_HLEN 14
#define ETH_FCS_LEN 4
#define GSW_statusOk 0
#define pr_info(...) ((void)0)
#define pr_debug(...) ((void)0)
#define pr_err(...) ((void)0)
#define max(a,b) ((a)>(b)?(a):(b))
CONSTANTS
REGISTER_TYPE
struct core_ops {
    struct {
        int (*RegisterGet)(void *,GSW_register_t *);
        int (*RegisterSet)(void *,GSW_register_t *);
    } gsw_common_ops;
    unsigned id;
};
struct ltq_eth_priv { int wan,jumbo_enabled,xgmac_id; struct { int num; } port[1]; };
struct net_device { int mtu,min_mtu,max_mtu; struct ltq_eth_priv priv; };
#define netdev_priv(dev) (&(dev)->priv)
static unsigned regs[2][0x1000];
static int calls, fail_at, absent[2], writes, fault_seen;
static struct core_ops cores[2];
static int allowed(unsigned addr) {
    if(addr==0x8c5 || addr==0xd05 || addr==0xd06) return 1;
    for(unsigned port=1;port<=5;port++) if(addr==0x8f9+12*port) return 1;
    return 0;
}
static int reg_get(void *c, GSW_register_t *r) {
    struct core_ops *core=c;
    assert(core->id<2 && r->nRegAddr<0x1000 && allowed(r->nRegAddr));
    calls++;
    if(calls==fail_at) { fault_seen=1;return -1; }
    r->nData=regs[core->id][r->nRegAddr];return 0;
}
static int reg_set(void *c, GSW_register_t *r) {
    struct core_ops *core=c;
    assert(core->id<2 && r->nRegAddr<0x1000 && allowed(r->nRegAddr));
    assert(r->nData<=0xffff);
    calls++;
    if(calls==fail_at) { fault_seen=1;return -1; }
    regs[core->id][r->nRegAddr]=r->nData;writes++;return 0;
}
static struct core_ops *gsw_get_swcore_ops(int id) { assert(id>=0 && id<2);return absent[id]?NULL:&cores[id]; }
static int g_eth_switch_mode=1;
struct mac_ops { void (*set_mtu)(void *,int); };
static struct mac_ops *gsw_get_mac_ops(int a,int b) { (void)a;(void)b;return NULL; }
CODE
static unsigned cases;
static struct net_device device(unsigned wan,unsigned port) {
    struct net_device dev={.mtu=1500,.min_mtu=68,.max_mtu=8000};
    dev.priv.wan=wan;dev.priv.port[0].num=port;dev.priv.xgmac_id=-1;return dev;
}
static void reset(void) {
    memset(regs,0,sizeof(regs));
    for(unsigned i=0;i<2;i++) {
        cores[i].id=i;cores[i].gsw_common_ops.RegisterGet=reg_get;
        cores[i].gsw_common_ops.RegisterSet=reg_set;absent[i]=0;
        regs[i][0x8c5]=1518;regs[i][0xd06]=2304;regs[i][0xd05]=0x21;
        for(unsigned port=1;port<=5;port++) regs[i][0x8f9+12*port]=0x41;
    }
    calls=fail_at=writes=fault_seen=0;
}
static void assert_limits(struct net_device *dev) {
    unsigned first=dev->priv.wan?1:0;
    for(unsigned i=first;i<2;i++) {
        assert((regs[i][0x8c5]&0x3fff)>=(unsigned)dev->mtu+ETH_HLEN+ETH_FCS_LEN);
        if(dev->mtu>1500) {
            assert(regs[i][0xd05]&8);
            /* Conservative budget includes Ethernet/FCS, two VLAN tags,
             * and PMAC. This is a configuration check, not a packet model.
             */
            assert((regs[i][0xd06]&0x3fff)>=(unsigned)dev->mtu+18+8+8);
        }
    }
    unsigned port=dev->priv.wan?1:dev->priv.port[0].num;
    assert(!!(regs[first][0x8f9+12*port]&8)==(dev->mtu>1500));
}
static void threshold_case(void) {
    reset();struct net_device d=device(0,2);
    assert(!ltq_change_mtu(&d,8000));
    printf("MTU %d: GSW-L PMAC=%u GSW-R PMAC=%u\n",d.mtu,regs[0][0xd06],regs[1][0xd06]);fflush(stdout);
    assert_limits(&d);cases++;
}
static void failure_case(void) {
    reset();struct net_device d=device(0,2);fail_at=1;
    int result=ltq_change_mtu(&d,8000);
    printf("Injected first register-read failure: return=%d MTU=%d\n",result,d.mtu);fflush(stdout);
    assert(result==-EIO && d.mtu==1500 && !d.priv.jumbo_enabled);cases++;
}
static void faults(unsigned wan,unsigned port,int initial,int target) {
    reset();struct net_device d=device(wan,port);
    assert(!ltq_change_mtu(&d,initial));calls=0;
    assert(!ltq_change_mtu(&d,target));int count=calls;
    for(int fail=1;fail<=count;fail++) {
        reset();d=device(wan,port);assert(!ltq_change_mtu(&d,initial));
        struct net_device before=d;calls=0;fail_at=fail;
        assert(ltq_change_mtu(&d,target)==-EIO);
        assert(fault_seen && !memcmp(&d,&before,sizeof(d)));
        /* All shared changes before a failed port update only enlarge the
         * accepted frame range. The old device MTU remains usable.
         */
        assert_limits(&d);
        fail_at=0;assert(!ltq_change_mtu(&d,target));assert_limits(&d);cases++;
    }
}
int main(void) {
    if(!strcmp("CASE","threshold")) { threshold_case();return 0; }
    if(!strcmp("CASE","failure")) { failure_case();return 0; }
    threshold_case();failure_case();
    for(unsigned dev=0;dev<5;dev++) {
        unsigned wan=dev==4,port=wan?1:dev+2;
        for(int mtu=0;mtu<=9583;mtu++) {
            reset();struct net_device d=device(wan,port),before=d;
            int valid=mtu>=68 && mtu<=8000;
            assert(ltq_change_mtu(&d,mtu)==(valid?0:-EINVAL));
            if(valid) { assert(d.mtu==mtu);assert_limits(&d); }
            else assert(!memcmp(&d,&before,sizeof(d)) && !calls && !writes);
            cases++;
        }
        faults(wan,port,1500,8000);faults(wan,port,2000,8000);
        faults(wan,port,8000,1500);faults(wan,port,1500,1492);
        /* No successful MTU change with a required switch absent. */
        for(unsigned sw=wan?1:0;sw<2;sw++) {
            reset();struct net_device d=device(wan,port),before=d;absent[sw]=1;
            assert(ltq_change_mtu(&d,8000)==-EIO && !memcmp(&d,&before,sizeof(d)));cases++;
        }
        /* Preserve the reserved high bits and larger shared frame limits. */
        reset();struct net_device d=device(wan,port);
        for(unsigned sw=0;sw<2;sw++) {
            regs[sw][0x8c5]|=0xc000;regs[sw][0xd06]|=0xc000;
        }
        assert(!ltq_change_mtu(&d,8000));assert_limits(&d);
        for(unsigned sw=wan?1:0;sw<2;sw++) {
            assert((regs[sw][0x8c5]&0xc000)==0xc000);
            assert((regs[sw][0xd06]&0xc000)==0xc000);
            regs[sw][0xd06]=0xc000|9500;
        }
        assert(!ltq_change_mtu(&d,1500));assert(!ltq_change_mtu(&d,2000));
        for(unsigned sw=wan?1:0;sw<2;sw++) assert(regs[sw][0xd06]==(0xc000|9500));
        cases++;
    }
    /* Lowering one LAN interface must not reduce shared limits or alter
     * another LAN/WAN port's jumbo enable bit.
     */
    reset();struct net_device lan=device(0,2),other=device(0,3),wan=device(1,1);
    assert(!ltq_change_mtu(&lan,8000));assert(!ltq_change_mtu(&other,7000));
    assert(!ltq_change_mtu(&wan,6000));assert(!ltq_change_mtu(&lan,1500));
    assert_limits(&lan);assert_limits(&other);assert_limits(&wan);cases++;
    printf("PASS: %u switch MTU/register cases; hardware API modeled, no traffic executed\n",cases);
}
'''
harness = harness.replace('\nCONSTANTS\n', '\n'+constants+'\n').replace('\nCODE\n', '\n'+code+'\n').replace('"CASE"', '"'+a.case+'"')
harness = harness.replace('\nREGISTER_TYPE\n', '\n'+register_type+'\n')

def run(path):
    path.mkdir(parents=True, exist_ok=True)
    (path/'probe.c').write_text(harness)
    opts = ['-static'] if a.qemu else ['-fno-pie', '-no-pie', '-fsanitize=address,undefined']
    subprocess.run([a.cc, '-O1', '-g', *opts, str(path/'probe.c'), '-o', str(path/'probe')], check=True)
    command = [str(path/'probe')]
    if a.qemu:
        command.insert(0, str(a.qemu.resolve()))
    subprocess.run(command, check=True, cwd=path)

if a.output:
    run(a.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='grx500-mtu-switch-') as tmp:
        run(Path(tmp))
