#!/usr/bin/env python3
"""Execute the actual data TX completion handler with DMA/VAP/pool stubs.

Models completion after VAP stop/removal and invalid completions. This does
not run firmware, interrupts, concurrent teardown or a hardware DMA engine.
"""
from pathlib import Path
import re
import subprocess
import argparse
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tree', type=Path)
p.add_argument('--before', type=Path)
p.add_argument('--cc', default='gcc')
p.add_argument('--qemu', type=Path)
p.add_argument('--output', type=Path)
a = p.parse_args()
current = (a.tree / 'wireless/driver/shared/hw_mmb.c').read_text()
source = a.before.read_text() if a.before else current

def extract(text, name):
    match = re.search(r'^static[^\n]*\n' + name + r'\s*\([^;]*?\)\s*\{', text, re.M)
    assert match
    end, depth = match.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end]

function = extract(current, 'wave_data_tx_unmap') + '\n' + extract(source, '_mtlk_mmb_handle_dat_cfm')

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t uint32;
typedef uint8_t uint8;
typedef unsigned UMI_STATUS;
#define __INLINE inline
#define __UNLIKELY(x) (x)
#define BD_DBG
#define LE32_TO_CPU(x) (x)
/* Fixture fields; this test does not validate firmware bit positions. */
#define TX_DATA_INFO_EP 0
#define TX_DATA_INFO_VAPID 0
#define MTLK_BFIELD_GET(x, field) (x)
#define HD_BD_INDEX_GET(hd) ((hd)->u32BdIndex & 0xffff)
#define MTLK_DATA_TO_DEVICE 1
#define MTLK_HW_RESET 1
#define UMI_OK 0
#define ELOG_D(...) ((void)0)
#define ELOG_DD(...) ((void)0)
#define ELOG_DDDD(...) ((void)0)
#define ILOG5_DDD(...) ((void)0)
#define mtlk_dump(...) ((void)0)
typedef struct { unsigned mapped; } nbuf;
typedef struct {
    nbuf *nbuf;
    bool dma_mapped;
    uint32 dma_addr, size, status, nof_retries;
    uint8 radio_id, vap_id;
} mtlk_hw_data_req_mirror_t;
typedef struct {
    uint32 u32BdIndex, u32frameInfo0, u32frameInfo1, u32HostPayloadAddr;
} HOST_DSC;
struct basic_bdr { mtlk_hw_data_req_mirror_t slots[2]; };
typedef struct {
    void *ccr, *radio_descr;
    struct {
        struct { unsigned size, read_ptr, write_ptr;
                 struct { unsigned IN_copy, int_OUT_cntr; } regs; } ring;
        struct { struct basic_bdr basic; } bdr_data;
        unsigned long used_bd_map[1];
    } tx;
} mtlk_hw_t;
typedef void *mtlk_vap_handle_t;
static unsigned live, mapped, unmaps, frees, callbacks, returned, resets;
static unsigned not_ready, absent, chosen_dma;
static int test_and_clear_bit(unsigned bit, unsigned long *map) {
    assert(bit < 2); unsigned old = (*map >> bit) & 1; *map &= ~(1UL << bit); return old;
}
static void __wave_hw_rx_hd_decode(mtlk_hw_t *hw, unsigned ep, unsigned vap,
                                  uint8 *radio_id, uint8 *vap_id) {
    (void)hw; *radio_id = ep; *vap_id = vap;
}
static mtlk_hw_data_req_mirror_t *lookup(struct basic_bdr *b, unsigned index) {
    assert(index < 2); return &b->slots[index];
}
#define _mtlk_basic_bdr_get_mirror_bd(b,i,t) lookup(b,i)
static int _mtlk_mmb_get_vap_is_not_ready(mtlk_hw_t *hw, unsigned r, unsigned v) {
    (void)hw; (void)r; (void)v; return not_ready;
}
static void * _mtlk_mmb_get_vap_handle_from_vap_id(mtlk_hw_t *hw, unsigned r, unsigned v) {
    (void)r; (void)v; return absent ? NULL : hw;
}
#define _mtlk_mmb_log_error_vap_not_ready(...) ((void)0)
#define _mtlk_mmb_log_error_vap_not_exist(...) ((void)0)
static void *mtlk_ccr_get_dev_ctx(void *p) { return p; }
static void mtlk_df_nbuf_unmap_phys_addr(void *dev, nbuf *n, unsigned dma,
                                       unsigned size, unsigned dir) {
    (void)dev; assert(n && n->mapped && dma == chosen_dma && size == 128);
    assert(dir == MTLK_DATA_TO_DEVICE);
    n->mapped = 0; mapped--; unmaps++;
}
static void mtlk_df_nbuf_free(nbuf *n) {
    if (!n) return;
    assert(!n->mapped && live); live--; frees++; free(n);
}
static int release_tx_data(void *vap, mtlk_hw_data_req_mirror_t *d) {
    assert(vap && !not_ready && !absent && d->status == UMI_OK && !d->nof_retries);
    callbacks++; mtlk_df_nbuf_free(d->nbuf); return 0;
}
static struct { int (*release_tx_data)(void *, mtlk_hw_data_req_mirror_t *); }
    vft = {release_tx_data};
#define mtlk_vap_get_core_vft(vap) (&vft)
static int _mtlk_mmb_free_sent_msg_to_data_pool(mtlk_hw_t *hw, mtlk_hw_data_req_mirror_t *d) {
    (void)hw; (void)d;
    if (live || mapped) fprintf(stderr, "Returning descriptor leaks live=%u mapped=%u\n", live, mapped);
    assert(!live && !mapped); returned++; return 0;
}
static void *wave_radio_descr_hw_api_get(void *r, unsigned id) { (void)id; return r; }
static void mtlk_hw_set_prop(void *api, unsigned prop, void *data, unsigned size) {
    (void)api; (void)data; assert(prop == MTLK_HW_RESET && !size); resets++;
}
FUNCTION
static mtlk_hw_data_req_mirror_t *init(mtlk_hw_t *hw, HOST_DSC *hd, int payload) {
    assert(!live && !mapped); memset(hw, 0, sizeof(*hw)); memset(hd, 0, sizeof(*hd));
    unmaps=frees=callbacks=returned=resets=not_ready=absent=0;
    hw->tx.ring.size=2; hw->tx.used_bd_map[0]=1;
    mtlk_hw_data_req_mirror_t *d=&hw->tx.bdr_data.basic.slots[0];
    hd->u32frameInfo0=d->vap_id=3; hd->u32frameInfo1=d->radio_id=1;
    d->nbuf=calloc(1,sizeof(*d->nbuf)); assert(d->nbuf); live++;
    if(payload) { d->dma_addr=chosen_dma; d->dma_mapped=true; d->size=128; d->nbuf->mapped=1; mapped++; }
    return d;
}
int main(void) {
    unsigned cases=0; mtlk_hw_t hw; HOST_DSC hd;
    for(unsigned address=0;address<2;address++) {
    chosen_dma=address*0x1000;
    for(int payload=1;payload>=0;payload--) for(unsigned state_i=0;state_i<3;state_i++) {
        unsigned state=(state_i+1)%3;
        mtlk_hw_data_req_mirror_t *d=init(&hw,&hd,payload);
        not_ready=state==1; absent=state==2;
        _mtlk_mmb_handle_dat_cfm(&hw,&hd);
        assert(!live && !mapped && returned==1 && frees==1 && unmaps==payload && !resets);
        assert(callbacks==(state==0));
        assert(!d->nbuf && !d->dma_addr && !d->dma_mapped);
        /* Duplicate completion must not free or return the descriptor again. */
        _mtlk_mmb_handle_dat_cfm(&hw,&hd);
        assert(resets==1 && returned==1 && frees==1 && unmaps==payload); cases+=2;
    }
    for(unsigned state=0;state<3;state++) for(unsigned fault=0;fault<4;fault++) {
        mtlk_hw_data_req_mirror_t *d=init(&hw,&hd,1);
        not_ready=state==1; absent=state==2;
        if(fault==0) hd.u32BdIndex=2;
        if(fault==1) hw.tx.used_bd_map[0]=0;
        if(fault==2) hd.u32frameInfo1=0;
        if(fault==3) hd.u32frameInfo0=4;
        _mtlk_mmb_handle_dat_cfm(&hw,&hd);
        assert(resets==1 && !returned && !unmaps && !frees && !callbacks);
        assert(live==1 && mapped==1);
        /* Invalid completions leave ownership to recovery, modeled here. */
        mtlk_df_nbuf_unmap_phys_addr(NULL,d->nbuf,d->dma_addr,d->size,1);
        mtlk_df_nbuf_free(d->nbuf); cases++;
    }
    }
    printf("PASS: %u data TX completion ownership cases\n",cases);
}
'''.replace('FUNCTION', function)

def run(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'probe.c').write_text(harness)
    flags = ['-static'] if a.qemu else ['-fno-pie', '-no-pie', '-fsanitize=address,undefined']
    subprocess.run([a.cc, '-std=gnu11', '-g', '-O1', *flags,
                    '-fno-omit-frame-pointer', str(path / 'probe.c'), '-o', str(path / 'probe')], check=True)
    command = [str(path / 'probe')]
    if a.qemu:
        command.insert(0, str(a.qemu.resolve()))
    subprocess.run(command, check=True, cwd=path)

if a.output:
    run(a.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-tx-completion-') as tmp:
        run(Path(tmp))
