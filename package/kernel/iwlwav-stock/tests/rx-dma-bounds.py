#!/usr/bin/env python3
"""Run the actual RX length rejection block with mapped/allocated size fixtures."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1])/'wireless/driver/shared/hw_mmb.c').read_text()
match = re.search(r'  if \(__UNLIKELY\(total_size >.*?\n  \}\n(?=\n  mtlk_df_nbuf_put)', source, re.S)
if not match:
    raise SystemExit('RX rejection block not found')
harness = r'''
#include <assert.h>
#include <stdio.h>
#define __UNLIKELY(x) (x)
#define ELOG_DDDD(...) ((void)0)
struct nbuf { unsigned tailroom; };
struct mirror { struct nbuf *nbuf; unsigned size; };
static unsigned mtlk_df_nbuf_get_tail_room_size(struct nbuf *n) { return n->tailroom; }
static int accepts(unsigned total_size, unsigned mapped, unsigned tailroom) {
 struct nbuf n={tailroom}; struct mirror m={&n,mapped}; struct mirror *data_ind=&m;
BLOCK
 return 1;
buf_return:
 return 0;
}
int main(void) {
 unsigned sizes[]={0,1,64,1518,4096,8192}, cases=0;
 // A legal 4095-byte length plus Gen6's 15-byte offset exceeds the 4096
 // mapped bytes, even when allocator rounding provides 4160 bytes of room.
 if (accepts(4110,4096,4160)) {
  fputs("RX accepted 4110 bytes from a 4096-byte DMA mapping\n",stderr);
  assert(0);
 }
 for (unsigned i=0;i<sizeof(sizes)/sizeof(sizes[0]);i++) {
  unsigned mapped=sizes[i];
  unsigned tails[]={mapped ? mapped-1 : 0, mapped, mapped+64};
  for (unsigned j=0;j<3;j++) {
   // Gen6 contributes up to 15 offset bytes; test every encoded offset.
   for (unsigned offset=0;offset<16;offset++) {
    for (unsigned length=0;length<=mapped+1;length++) {
     unsigned total=offset+length;
     int expected=total<=mapped && total<=tails[j];
     int actual=accepts(total,mapped,tails[j]);
     if (actual!=expected) fprintf(stderr,"mapped=%u allocated=%u offset=%u length=%u accepted=%d\n",mapped,tails[j],offset,length,actual);
     assert(actual==expected); cases++;
    }
   }
  }
 }
 printf("%u RX DMA/allocation boundary cases passed (ASan/UBSan; extracted production branch).\n",cases);
}
'''.replace('BLOCK', match.group())
with tempfile.TemporaryDirectory(prefix='wave-rx-bounds-') as temp:
    temp = Path(temp)
    (temp/'test.c').write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(temp/'test.c'), '-o', str(temp/'test')], check=True)
    subprocess.run([str(temp/'test')], check=True)
