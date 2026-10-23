#!/usr/bin/env python3
"""Execute data TX submission/rejection and unconfirmed-buffer cleanup.

Uses actual driver functions, mirror declaration and bitfield definitions.
DMA, ring publication, reset and list operations are fixtures, not hardware.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tree', type=Path)
p.add_argument('--before', type=Path)
p.add_argument('--case', choices=['all', 'reject', 'zero'], default='all')
p.add_argument('--cc', default='gcc')
p.add_argument('--qemu', type=Path)
p.add_argument('--output', type=Path)
a = p.parse_args()
current = (a.tree / 'wireless/driver/shared/hw_mmb.c').read_text()
source = a.before.read_text() if a.before else current

def extract(text, name):
    m = re.search(r'^static (?:int|void)\s*\n' + name + r'\s*\([^;]*?\)\s*\{', text, re.M)
    assert m, name
    end, depth = m.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[m.start():end]

header = (a.tree / 'wireless/driver/shared/hw_hal.h').read_text()
end = header.index('} mtlk_hw_data_req_mirror_t;') + len('} mtlk_hw_data_req_mirror_t;')
mirror = header[header.rindex('typedef struct', 0, end):end]
fields = '\n'.join(line for line in (a.tree / 'wireless/shared_mbss_mac/mhi_umi.h').read_text().splitlines()
                   if re.match(r'#define TX_DATA_INFO_\w+\s+MTLK_BFIELD_INFO', line))
bits = (a.tree / 'wireless/shared/mtlkbfield.h').read_text()
# Before-source tests use the current unmap helper only for fixture cleanup.
functions = extract(current, 'wave_data_tx_unmap') + '\n' + '\n'.join(
    extract(source, name) for name in ['_mtlk_hw_send_data', '_mtlk_hw_release_msg_to_send',
                                     '_mtlk_mmb_free_unconfirmed_tx_buffers'])
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <endian.h>
typedef uint32_t uint32;
typedef uint16_t uint16;
typedef uint8_t uint8;
typedef unsigned UMI_STATUS;
typedef unsigned mtlk_osal_timestamp_t;
typedef struct { unsigned mapped, addr, size; } mtlk_nbuf_t;
typedef struct list_node { struct list_node *next; } mtlk_dlist_entry_t;
typedef struct { unsigned index; mtlk_dlist_entry_t list_entry; } mtlk_hw_mirror_hdr_t;
MIRROR
BITS
FIELDS
#define BD_DBG
#define __UNLIKELY(x) (x)
#define CPU_TO_LE32(x) htole32(x)
#define MTLK_ERR_OK 0
#define MTLK_ERR_PKT_DROPPED -1
#define MTLK_DATA_TO_DEVICE 1
#define MTLK_HW_RESET 1
#define CPU_STAT_ID_TX_HW 0
#define CPU_STAT_BEGIN_TRACK(x) (++tracks)
#define CPU_STAT_END_TRACK(x) (--tracks)
#define DB_UNKNOWN_SID 255
#define NO_FRAG 3
#define TRUE 1
#define ELOG_D(...) ((void)0)
#define ILOG4_DP(...) ((void)0)
#define ILOG3_V(...) ((void)0)
typedef struct { uint32 u32BdIndex,u32frameInfo0,u32frameInfo1,u32frameInfo3,u32HostPayloadAddr; } HOST_DSC;
typedef struct { unsigned size; } ring_t;
typedef struct { void *ccr; struct {
    ring_t ring;
    unsigned long used_bd_map[1];
    struct { mtlk_dlist_entry_t *used_list; } bdr_data;
} tx; } mtlk_hw_t;
typedef void *mtlk_vap_handle_t;
typedef void mtlk_hw_msg_t;
#define DATA_REQ_MIRROR_PTR(x) ((mtlk_hw_data_req_mirror_t *)(x))
static unsigned maps,unmaps,live,freed,returned,published,resets,map_failed,next_addr;
static int tracks;
static HOST_DSC last;
static unsigned mtlk_vap_get_id(void *v) { assert(v); return 3; }
static unsigned wave_vap_radio_id_get(void *v) { assert(v); return 1; }
static unsigned wave_vap_ep_bit_get(void *v) { assert(v); return 1; }
static void *mtlk_vap_get_hwapi(void *v) { return v; }
static void *mtlk_ccr_get_dev_ctx(void *v) { return v; }
static unsigned mtlk_df_nbuf_map_to_phys_addr(void *dev,mtlk_nbuf_t *n,unsigned size,unsigned dir) {
    (void)dev;assert(n && !n->mapped && size && dir==1);
    if(map_failed) return UINT32_MAX;
    n->mapped=1;n->addr=next_addr;n->size=size;maps++;return next_addr;
}
static int dma_mapping_error(void *dev,unsigned addr) { (void)dev;return addr==UINT32_MAX; }
static void mtlk_df_nbuf_unmap_phys_addr(void *dev,mtlk_nbuf_t *n,unsigned addr,unsigned size,unsigned dir) {
    (void)dev;assert(n && n->mapped && addr==n->addr && size==n->size && dir==1);
    n->mapped=0;unmaps++;
}
static void mtlk_df_nbuf_free(mtlk_nbuf_t *n) {
    if(!n)return;
    if(n->mapped) fprintf(stderr,"packet freed while DMA mapping remains at %#x\n",n->addr);
    assert(!n->mapped && live);live--;freed++;free(n);
}
static int test_and_set_bit(unsigned bit,unsigned long *map) {
    assert(bit<4);int old=!!(*map&(1UL<<bit));*map|=1UL<<bit;return old;
}
static void mtlk_hw_set_prop(void *v,unsigned prop,void *data,unsigned size) {
    assert(v && prop==1 && !data && !size);resets++;
}
static void _mtlk_mmb_put_hd_to_ring(mtlk_hw_t *hw,HOST_DSC *hd,ring_t *ring) {
    assert(ring==&hw->tx.ring);last=*hd;published++;
}
static int _mtlk_mmb_free_sent_msg_to_data_pool(mtlk_hw_t *hw,mtlk_hw_data_req_mirror_t *d) {
    (void)hw;assert(!d->dma_mapped && !d->dma_addr && !d->nbuf);returned++;return 0;
}
static mtlk_dlist_entry_t *mtlk_dlist_pop_front(mtlk_dlist_entry_t **list) {
    mtlk_dlist_entry_t *node=*list;if(node)*list=node->next;return node;
}
#define MTLK_LIST_GET_CONTAINING_RECORD(node,type,member) ((type *)((char *)(node)-offsetof(type,member)))
FUNCTIONS
static void reset(void) {
    assert(!live && maps==unmaps);maps=unmaps=freed=returned=published=resets=map_failed=next_addr=0;tracks=0;
}
static void init_req(mtlk_hw_data_req_mirror_t *r,unsigned size) {
    memset(r,0,sizeof(*r));r->size=size;r->nbuf=calloc(1,sizeof(*r->nbuf));assert(r->nbuf);live++;
    r->sid=7;r->tid=2;r->frame_type=1;
}
static void submit(unsigned size,unsigned addr,unsigned fail,unsigned fault) {
    reset();mtlk_hw_t hw={.tx.ring.size=4};mtlk_hw_data_req_mirror_t d;init_req(&d,size);
    next_addr=addr;map_failed=fail;
    if(fault==1)d.hdr.index=4;
    if(fault==2)hw.tx.used_bd_map[0]=1;
    mtlk_nbuf_t *packet=d.nbuf;
    int result=_mtlk_hw_send_data(&hw,&hw,&d);
    bool mapping_failed=size && fail;
    bool rejected=mapping_failed || fault;
    assert(result==(rejected?MTLK_ERR_PKT_DROPPED:MTLK_ERR_OK));
    if(rejected) {
        if(maps!=unmaps)fprintf(stderr,"rejected TX leaked mapping: maps=%u unmaps=%u\n",maps,unmaps);
        assert(maps==unmaps && !d.dma_mapped && !d.dma_addr && !published);
        assert(resets==(!mapping_failed && fault));
        assert(hw.tx.used_bd_map[0]==(fault==2));
        assert(!tracks);
        _mtlk_hw_release_msg_to_send(&hw,&d);
        assert(returned==1 && !d.nbuf);mtlk_df_nbuf_free(packet);
    } else {
        assert(published==1 && !resets && !tracks && hw.tx.used_bd_map[0]==1);
        assert(d.dma_mapped==!!size && packet->mapped==!!size);
        assert(le32toh(last.u32HostPayloadAddr)==(size?(addr&~7U):0));
        unsigned info=le32toh(last.u32frameInfo3);
        assert(MTLK_BFIELD_GET(info,TX_DATA_INFO_LENGTH)==size);
        assert(MTLK_BFIELD_GET(info,TX_DATA_INFO_OFFSET)==(size?(addr&7):0));
        wave_data_tx_unmap(&hw,&d);wave_data_tx_unmap(&hw,&d);
        assert(!d.dma_mapped && !d.dma_addr && unmaps==!!size);
        mtlk_df_nbuf_free(packet);
    }
    assert(!live && maps==unmaps && freed==1);
}
static void recover(unsigned count,unsigned zero,unsigned partial) {
    reset();mtlk_hw_t hw={.tx.ring.size=4};mtlk_hw_data_req_mirror_t slots[4];
    for(unsigned i=0;i<count;i++) {
        init_req(&slots[i],128);next_addr=zero?0:0x1000+i*128;
        if(!partial || i%2) {
            slots[i].dma_addr=mtlk_df_nbuf_map_to_phys_addr(NULL,slots[i].nbuf,128,1);
            slots[i].dma_mapped=true;
        }
        slots[i].hdr.list_entry.next=hw.tx.bdr_data.used_list;
        hw.tx.bdr_data.used_list=&slots[i].hdr.list_entry;
    }
    _mtlk_mmb_free_unconfirmed_tx_buffers(&hw);
    assert(!live && unmaps==maps && freed==count && !hw.tx.bdr_data.used_list);
    for(unsigned i=0;i<count;i++)assert(!slots[i].nbuf && !slots[i].dma_addr && !slots[i].dma_mapped);
    _mtlk_mmb_free_unconfirmed_tx_buffers(&hw);assert(freed==count && unmaps==maps);
}
int main(void) {
    if(!strcmp("CASE","reject")){submit(128,0x1000,0,1);return 0;}
    if(!strcmp("CASE","zero")){recover(1,1,0);return 0;}
    unsigned cases=0,sizes[]={0,1,128,1500,65535},addrs[]={0,1,7,0x1000,0x1007};
    for(unsigned i=0;i<5;i++)for(unsigned j=0;j<5;j++)for(unsigned fail=0;fail<2;fail++)for(unsigned fault=0;fault<3;fault++) {
        submit(sizes[i],addrs[j],fail,fault);cases++;
    }
    for(unsigned count=0;count<=4;count++)for(unsigned zero=0;zero<2;zero++)for(unsigned partial=0;partial<2;partial++) {
        recover(count,zero,partial);cases++;
    }
    printf("PASS: %u data TX submission/rejection and recovery ownership cases (modeled DMA/ring/list)\n",cases);
}
'''
for key, value in [('MIRROR', mirror), ('BITS', bits), ('FIELDS', fields), ('FUNCTIONS', functions)]:
    harness = harness.replace('\n' + key + '\n', '\n' + value + '\n')
harness = harness.replace('"CASE"', '"' + a.case + '"')

def run(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'probe.c').write_text(harness)
    flags = ['-static'] if a.qemu else ['-fno-pie', '-no-pie', '-fsanitize=address,undefined']
    subprocess.run([a.cc, '-std=gnu11', '-O1', '-g', *flags, str(path / 'probe.c'), '-o', str(path / 'probe')], check=True)
    command = [str(path / 'probe')]
    if a.qemu:
        command.insert(0, str(a.qemu.resolve()))
    subprocess.run(command, check=True, cwd=path)

if a.output:
    run(a.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-data-tx-') as tmp:
        run(Path(tmp))
