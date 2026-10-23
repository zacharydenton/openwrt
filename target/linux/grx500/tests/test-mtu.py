#!/usr/bin/env python3
"""Exercise real CBM/datapath/netdev MTU helpers with platform leaf fixtures."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1] / 'files'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--api-source', type=Path, default=root / 'drivers/net/datapath/dpm/datapath_api.c')
a = p.parse_args()

def extract(path, name):
    source = path.read_text()
    match = re.search(r'^(?:static )?int ' + name + r'\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]

cbm = extract(root / 'drivers/net/ethernet/lantiq/cqm/grx500/cbm.c', 'cbm_get_mtu_size_grx500')
api = extract(a.api_source, 'dp_get_mtu_size')
eth = root / 'drivers/net/ethernet/lantiq/ltq_eth_drv_xrx500.c'
configure = extract(eth, 'ltq_configure_mtu_limits')
change = extract(eth, 'ltq_change_mtu')
headers = (root / 'include/net/datapath_api_gswip30.h').read_text()
pmac = re.search(r'struct pmac_rx_hdr \{.*?\n\} __packed;', headers, re.S).group(0)
harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
#define __packed __attribute__((packed))
PMAC
#define CONFIG_INTEL_DATAPATH_HAL_GSWIP30 1
#define IS_ENABLED(x) (x)
#define unlikely(x) (x)
#define likely(x) (x)
#define pr_err(...) ((void)0)
#define DP_FAILURE -1
#define DP_SUCCESS 0
#define CBM_FAILURE -1
#define CBM_SUCCESS 0
#define ETH_HLEN 14
#define ETH_FCS_LEN 4
#define ETH_DATA_LEN 1500
#define VLAN_HLEN 4
#define LTQ_ETH_MIN_MTU 68
/* Port geometry: 128 DMA headroom + 2 IP alignment + 64 NET_SKB_PAD.
 * PKT_DATA_OFFSET = 40 parser flags + 8 offsets + 8-byte PMAC.
 * These constants are audited against the compiled configuration/types.
 */
#define CBM_FIXED_RX_OFFSET 194
#define PKT_DATA_OFFSET (40 + 8 + sizeof(struct pmac_rx_hdr))
#define CONFIG_CBM_JBO_PKT_SIZE pool_size
#define min(a,b) ((a)<(b)?(a):(b))
#define clamp_t(t,v,l,h) ((t)(v)<(t)(l)?(t)(l):((t)(v)>(t)(h)?(t)(h):(t)(v)))
static unsigned pool_size=16384;
static int ready=1, dp_init_ok=1, fail_cbm;
struct cbm_mtu { int mtu; };
struct ltq_eth_priv { int num_port, xgmac_id,wan,jumbo_enabled; };
struct net_device { int mtu,min_mtu,max_mtu; struct ltq_eth_priv priv; };
static struct { unsigned mtu_limit; } g_soc_data={8000};
static int grx500_cbm_ready(void) { return ready; }
CBM
static int cbm_get_mtu_size(struct cbm_mtu *mtu) {
    if(fail_cbm) return CBM_FAILURE;
    return cbm_get_mtu_size_grx500(mtu);
}
API
CONFIGURE
#define netdev_priv(dev) (&(dev)->priv)
static int g_eth_switch_mode=1, writes, fail_jumbo;
struct mac_ops { void (*set_mtu)(void *,int); };
static struct mac_ops *gsw_get_mac_ops(int a,int b) { (void)a;(void)b;return NULL; }
static int ltq_set_max_pkt_len(struct ltq_eth_priv *p,u16 n) { (void)p;assert(n<=8000);writes++;return 0; }
static int enable(struct net_device *dev) { (void)dev;writes++;return fail_jumbo?-EIO:0; }
#define ltq_enable_gsw_l_jumbo enable
#define ltq_enable_gsw_r_jumbo enable
#define ltq_enable_gsw_r_pmac_jumbo enable
static int disable(struct net_device *dev) { (void)dev;writes++;return 0; }
#define ltq_disable_gsw_l_jumbo disable
#define ltq_disable_gsw_r_jumbo disable
CHANGE
int main(void) {
    unsigned cases=0; u32 out=0xfeedbeef;
    assert(dp_get_mtu_size(NULL,&out)==DP_SUCCESS);
    if(out!=16112) fprintf(stderr,"MTU query returned %u, expected 16112\n",out);
    assert(out==16112); cases++;
    assert(dp_get_mtu_size(NULL,NULL)==DP_FAILURE); cases++;
    assert(cbm_get_mtu_size_grx500(NULL)==CBM_FAILURE); cases++;
    for(unsigned fault=0;fault<4;fault++) {
        struct net_device d={.mtu=1500,.min_mtu=68,.max_mtu=1500}, before=d;
        ready=fault!=0;dp_init_ok=fault!=1;fail_cbm=fault==2;
        pool_size=fault==3?256:16384;
        assert(ltq_configure_mtu_limits(&d)==-EINVAL);
        assert(!memcmp(&d,&before,sizeof(d)));cases++;
    }
    ready=dp_init_ok=1;fail_cbm=0;
    for(unsigned pool=8192;pool<=16384;pool*=2) {
        pool_size=pool;
        struct net_device d={.mtu=1500,.min_mtu=68,.max_mtu=1500};
        assert(!ltq_configure_mtu_limits(&d));
        assert(d.max_mtu==(pool==8192?7920:8000));
        assert(d.min_mtu==68 && d.mtu==1500);cases++;
        for(int mtu=0;mtu<=9583;mtu++) {
            struct net_device n=d;writes=0;
            int valid=mtu>=68 && mtu<=d.max_mtu;
            int result=ltq_change_mtu(&n,mtu);
            assert(result==(valid?0:-EINVAL));
            if(valid) {
                assert(n.mtu==mtu && writes>0);
                assert((unsigned)mtu+ETH_HLEN+PKT_DATA_OFFSET+2*VLAN_HLEN+CBM_FIXED_RX_OFFSET<=pool);
            } else assert(n.mtu==1500 && !writes);
            cases++;
        }
    }
    pool_size=16384;
    for(unsigned wan=0;wan<2;wan++) {
        struct net_device d={.mtu=1500,.min_mtu=68,.max_mtu=1500};d.priv.wan=wan;
        assert(!ltq_configure_mtu_limits(&d));
        fail_jumbo=1;assert(ltq_change_mtu(&d,8000)==-EIO && d.mtu==1500);cases++;
        fail_jumbo=0;assert(!ltq_change_mtu(&d,8000) && d.priv.jumbo_enabled);cases++;
        assert(!ltq_change_mtu(&d,1500) && !d.priv.jumbo_enabled);cases++;
    }
    printf("PASS: %u MTU capacity, registration and change cases (mocked hardware)\n",cases);
}
'''
for token, code in [('PMAC', pmac), ('CBM', cbm), ('API', api), ('CONFIGURE', configure), ('CHANGE', change)]:
    harness = harness.replace('\n'+token+'\n', '\n'+code+'\n')
with tempfile.TemporaryDirectory(prefix='grx500-mtu-') as tmp:
    path=Path(tmp)
    (path/'probe.c').write_text(harness)
    subprocess.run(['gcc','-O1','-g','-fno-pie','-no-pie','-fsanitize=address,undefined',
                    str(path/'probe.c'),'-o',str(path/'probe')],check=True)
    subprocess.run([str(path/'probe')],check=True,cwd=path)
