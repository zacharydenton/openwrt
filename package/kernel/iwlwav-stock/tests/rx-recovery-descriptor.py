#!/usr/bin/env python3
"""Check actual recovery descriptor publication with poisoned stack locals.

The list, allocation and ring-write leaves are mocked. Only descriptor
initialization and the function's publication/failure control flow are tested.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
source = (root/'wireless/driver/shared/hw_mmb.c').read_text()
start = source.index('static void\n_mtlk_mmb_recover_rx_buffers ')
end = source.index('\nstatic uint32 __MTLK_IFUNC', start)
header = (root/'wireless/shared_mbss_mac/mhi_descriptors.h').read_text()
desc = re.search(r'typedef struct _HOST_DSC\s*\{.*?\} __MTLK_PACKED HOST_DSC;', header, re.S).group()
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t uint32;
typedef uint16_t uint16;
#define __MTLK_PACKED __attribute__((packed))
DESCRIPTOR
typedef struct { int dummy; } mtlk_lslist_entry_t;
typedef struct { mtlk_lslist_entry_t pend_l; struct {unsigned index;} hdr; unsigned dma_addr,size; } mtlk_hw_data_ind_mirror_t;
typedef struct { struct { struct {mtlk_lslist_entry_t *lbufs;} pending; int ring; } rx; } mtlk_hw_t;
static int fail, published, allocated;
static HOST_DSC captured;
#define MTLK_ERR_UNKNOWN -1
#define MTLK_ERR_OK 0
#define CPU_TO_LE32(x) (x)
#define NO_FRAG 3
// These fake field positions test initialization/control flow, not the wire ABI.
#define TX_DATA_INFO_SOP_EOP 0
#define TX_DATA_INFO_OFFSET 2
#define TX_DATA_INFO_LENGTH 5
#define MTLK_BFIELD_VALUE(field,val,type) ((type)(val) << (field))
#define MTLK_LIST_GET_CONTAINING_RECORD(p,t,m) ((t *)(p))
#define _mtlk_mmb_hw_inc_cnt(...) ((void)0)
#define ILOG2_DD(...) ((void)0)
static mtlk_lslist_entry_t *mtlk_lslist_pop(mtlk_lslist_entry_t **head) {mtlk_lslist_entry_t *p=*head;*head=NULL;return p;}
static void mtlk_lslist_push(mtlk_lslist_entry_t **head,mtlk_lslist_entry_t *p) {assert(!*head);*head=p;}
static int _mtlk_mmb_alloc_and_set_rx_buffer(mtlk_hw_t *hw,mtlk_hw_data_ind_mirror_t *slot) {
 (void)hw;(void)slot;allocated++;return fail ? -1 : 0;
}
static void _mtlk_mmb_put_hd_to_ring(mtlk_hw_t *hw,HOST_DSC *hd,int *ring) {
 assert(ring==&hw->rx.ring);captured=*hd;published++;
}
FUNCTION
int main(void) {
 mtlk_hw_t hw={0};mtlk_hw_data_ind_mirror_t slot={0};unsigned cases=0;
 for(unsigned offset=0;offset<8;offset++) {
  slot.hdr.index=17;slot.dma_addr=0x12340+offset;slot.size=4096;
  hw.rx.pending.lbufs=&slot.pend_l;published=allocated=fail=0;
  _mtlk_mmb_recover_rx_buffers(&hw,1);
  assert(published==1 && allocated==1 && !hw.rx.pending.lbufs);
  if(captured.u32frameInfo0 || captured.u32frameInfo1)
   fprintf(stderr,"uninitialized recovery fields: %08x %08x\n",captured.u32frameInfo0,captured.u32frameInfo1);
  assert(captured.u32frameInfo0==0 && captured.u32frameInfo1==0);
  assert(captured.u32BdIndex==17 && captured.u32HostPayloadAddr==0x12340);
  assert(captured.u32frameInfo3==(3 | (offset<<2) | (4096<<5)));cases++;
 }
 hw.rx.pending.lbufs=&slot.pend_l;published=allocated=0;fail=1;
 _mtlk_mmb_recover_rx_buffers(&hw,2);
 assert(!published && allocated==1 && hw.rx.pending.lbufs==&slot.pend_l);cases++;
 hw.rx.pending.lbufs=NULL;published=allocated=0;fail=0;
 _mtlk_mmb_recover_rx_buffers(&hw,2);assert(!published && !allocated);cases++;
 hw.rx.pending.lbufs=&slot.pend_l;
 _mtlk_mmb_recover_rx_buffers(&hw,0);assert(!published && !allocated && hw.rx.pending.lbufs);cases++;
 printf("%u recovery descriptor/control-flow cases passed (poisoned stack, ASan/UBSan; mocked ring).\n",cases);
}
'''.replace('DESCRIPTOR',desc).replace('FUNCTION',source[start:end])
with tempfile.TemporaryDirectory(prefix='wave-recovery-desc-') as temp:
    temp = Path(temp)
    (temp/'test.c').write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-ftrivial-auto-var-init=pattern', '-fsanitize=address,undefined',
                    str(temp/'test.c'), '-o', str(temp/'test')], check=True)
    subprocess.run([str(temp/'test')], check=True)
