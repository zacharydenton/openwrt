#!/usr/bin/env python3
"""Fault-inject the actual RX preallocation/cleanup functions with DMA stubs."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1])/'wireless/driver/shared/hw_mmb.c').read_text()
def function(name):
    match = re.search(r'^static[^\n]*\n'+re.escape(name)+r'\s*\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    start, brace = match.start(), match.end()-1
    level = 1
    end = brace+1
    while level:
        level += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

names = ['_mtlk_mmb_rx_free_all_fragments', '_mtlk_mmb_prealloc_and_set_rx_data_buffer',
         '_mtlk_mmb_free_preallocated_rx_data_buffers', '_mtlk_mmb_prealloc_rx_data_buffers']
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef unsigned uint32;
#define __INLINE inline
#define HW_FLAGS_PREPARED_RX_DATA_BUFFERS 256
#define RX_DATA_FRAME_SIZE 4096
#define RX_DATA_QUE_POS 0
#define MTLK_ERR_NO_MEM -1
#define MTLK_ERR_OK 0
#define MTLK_DATA_FROM_DEVICE 0
#define MTLK_ASSERT(...) ((void)0)
#define ILOG2_D(...) ((void)0)
#define ILOG2_DDDD(...) ((void)0)
typedef struct nbuf { struct nbuf *next; unsigned id; int mapped; } mtlk_nbuf_t;
typedef struct { mtlk_nbuf_t *nbuf; uint32 dma_addr, size, que_idx; struct {unsigned index;} hdr; } mtlk_hw_data_ind_mirror_t;
struct bdr { mtlk_hw_data_ind_mirror_t slots[8]; unsigned nof_bds; };
typedef struct {
 unsigned flags; int direct; void *ccr;
 struct { struct bdr bdr_data; mtlk_nbuf_t *first_fragment,*last_fragment; } rx;
 struct { struct { struct { unsigned u32NumRdsInPool; } sRdPOOL; } sBasic; } chi_area;
} mtlk_hw_t;
#define _mtlk_basic_bdr_get_mirror_bd(b,i,type) (&(b)->slots[i])
static unsigned allocation_calls, map_calls, unmaps, frees, live, mapped, published;
static int fail_alloc, fail_map;
static mtlk_nbuf_t *registry[128];
static int mtlk_mmb_dcdp_path_available(mtlk_hw_t *hw) { return hw->direct; }
static void *mtlk_ccr_get_dev_ctx(void *p) { return p; }
static mtlk_nbuf_t *_mtlk_mmb_nbuf_alloc(unsigned size) {
 assert(size==RX_DATA_FRAME_SIZE);
 unsigned id=++allocation_calls;
 if ((int)id==fail_alloc) return NULL;
 mtlk_nbuf_t *n=calloc(1,sizeof(*n)); assert(n); n->id=id; registry[id]=n; live++; return n;
}
static unsigned mtlk_df_nbuf_map_to_phys_addr(void *dev,mtlk_nbuf_t *n,unsigned size,int direction) {
 (void)dev; (void)direction; assert(n && !n->mapped && size==RX_DATA_FRAME_SIZE);
 if ((int)++map_calls==fail_map) return UINT32_MAX;
 n->mapped=1; mapped++; return n->id; // non-address token, never dereferenced
}
static int dma_mapping_error(void *dev,unsigned dma) { (void)dev; return dma==UINT32_MAX; }
static void mtlk_df_nbuf_unmap_phys_addr(void *dev,mtlk_nbuf_t *n,unsigned dma,unsigned size,int direction) {
 (void)dev; (void)direction;
 assert(n && n->mapped && n->id==dma && size==RX_DATA_FRAME_SIZE);
 n->mapped=0; mapped--; unmaps++;
}
static void _mtlk_mmb_nbuf_free(mtlk_nbuf_t *n) {
 assert(n && !n->mapped && registry[n->id]==n);
 registry[n->id]=NULL; live--; frees++; free(n);
}
#define mtlk_df_nbuf_free _mtlk_mmb_nbuf_free
static void _mtlk_mmb_set_rdpool_entry(mtlk_hw_t *hw,unsigned dma,unsigned index) {
 assert(hw->rx.bdr_data.slots[index].nbuf==registry[dma] && registry[dma]->mapped); published++;
}
FUNCTIONS
static void init(mtlk_hw_t *hw) {
 assert(!live && !mapped); memset(hw,0,sizeof(*hw)); memset(registry,0,sizeof(registry));
 allocation_calls=map_calls=unmaps=frees=published=0; fail_alloc=fail_map=0;
 hw->rx.bdr_data.nof_bds=hw->chi_area.sBasic.sRdPOOL.u32NumRdsInPool=8;
 for (unsigned i=0;i<8;i++) hw->rx.bdr_data.slots[i].hdr.index=i;
}
static void clean(mtlk_hw_t *hw) {
 _mtlk_mmb_free_preallocated_rx_data_buffers(hw);
 if(live || mapped) fprintf(stderr,"cleanup leaked live=%u mapped=%u\n",live,mapped);
 assert(!live && !mapped && !(hw->flags & HW_FLAGS_PREPARED_RX_DATA_BUFFERS));
 assert(!hw->rx.first_fragment && !hw->rx.last_fragment);
 for(unsigned i=0;i<8;i++) assert(!hw->rx.bdr_data.slots[i].nbuf);
 unsigned old_frees=frees, old_unmaps=unmaps;
 _mtlk_mmb_free_preallocated_rx_data_buffers(hw);
 assert(frees==old_frees && unmaps==old_unmaps);
}
int main(void) {
 mtlk_hw_t hw; unsigned cases=0;
 if(getenv("WAVE_RX_TEST_FRAGMENTS_ONLY")) goto fragments;
 for (unsigned mode=0;mode<2;mode++) for(unsigned index=1;index<=8;index++) {
  init(&hw); if(mode) fail_map=index; else fail_alloc=index;
  assert(_mtlk_mmb_prealloc_rx_data_buffers(&hw)==MTLK_ERR_NO_MEM);
  // The failed initialization step itself must release all prior mappings.
  if(live || mapped) fprintf(stderr,"failure mode=%u slot=%u leaked live=%u mapped=%u\n",mode,index,live,mapped);
  assert(!live && !mapped); clean(&hw); cases++;
 }
 init(&hw); assert(_mtlk_mmb_prealloc_rx_data_buffers(&hw)==MTLK_ERR_OK);
 assert(live==8 && mapped==8 && published==8); clean(&hw); cases++;
 // Model two received fragments: unmap each old buffer, retain it on the
 // fragment chain, then replace its ring slot with a fresh mapped buffer.
fragments:
 init(&hw); assert(_mtlk_mmb_prealloc_rx_data_buffers(&hw)==MTLK_ERR_OK);
 for(unsigned i=0;i<2;i++) {
  mtlk_hw_data_ind_mirror_t *slot=&hw.rx.bdr_data.slots[i]; mtlk_nbuf_t *old=slot->nbuf;
  mtlk_df_nbuf_unmap_phys_addr(NULL,old,slot->dma_addr,slot->size,0);
  if(i) hw.rx.last_fragment->next=old; else hw.rx.first_fragment=old;
  hw.rx.last_fragment=old;
  assert(_mtlk_mmb_prealloc_and_set_rx_data_buffer(&hw,slot)==MTLK_ERR_OK);
 }
 assert(live==10 && mapped==8); clean(&hw); cases++;
 init(&hw); hw.direct=1;
 assert(_mtlk_mmb_prealloc_rx_data_buffers(&hw)==MTLK_ERR_OK);
 assert(!live && !mapped && !allocation_calls); clean(&hw); cases++;
 printf("%u RX allocation/cleanup ownership cases passed (ASan/UBSan; mocked DMA).\n",cases);
}
'''.replace('FUNCTIONS', '\n'.join(function(name) for name in names))
with tempfile.TemporaryDirectory(prefix='wave-rx-ownership-') as temp:
    temp = Path(temp)
    (temp/'test.c').write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(temp/'test.c'), '-o', str(temp/'test')], check=True)
    subprocess.run([str(temp/'test')], check=True)
