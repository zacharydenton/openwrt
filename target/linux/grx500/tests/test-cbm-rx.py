#!/usr/bin/env python3
"""Exercise the actual CBM-to-Linux copy helper with bounded hardware pools.

DMA/cache operations are recorded, not emulated. The 248-byte shared-info
fixture is the MIPS layout measured in this port's linked vmlinux with pahole.
Host addresses for the two pools must fit the driver's 32-bit address API.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] /
               'files/drivers/net/ethernet/lantiq/cqm/grx500/cbm.c')
p.add_argument('--jumbo-size', type=int, choices=(8192, 16384), default=16384)
a = p.parse_args()
source = a.source.read_text()
start = source.index('static struct sk_buff *build_skb_grx500(')
helper = source[start:source.index('\n/*FSQM initialization', start)]
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
typedef uint32_t u32;
typedef uintptr_t dma_addr_t;
typedef int gfp_t;
#define SBA0_STD 1
#define SBA0_JBO 2
#define CBM_STD_BUF_SIZE 2048
#define CONFIG_CBM_JBO_PKT_SIZE JUMBO_SIZE
#define DMA_BIDIRECTIONAL 0
#define SKB_DATA_ALIGN(x) (((x) + 31U) & ~31U)
struct skb_shared_info { unsigned char fixture[248]; };
struct sk_buff { unsigned char *data; size_t capacity; };
static unsigned char standard[2048] __attribute__((aligned(8192)));
static unsigned char jumbo[CONFIG_CBM_JBO_PKT_SIZE] __attribute__((aligned(CONFIG_CBM_JBO_PKT_SIZE)));
static struct { void *dev; } g_cbm_ctrl;
static int allocation_failure, dma_failure, allocated, freed, synced, returned;
static unsigned char *expected_pool;
static u32 expected_capacity;
static int check_ptr_valid_type(u32 address) {
 if (address >= (uintptr_t)standard && address < (uintptr_t)standard+sizeof(standard)) return SBA0_STD;
 if (address >= (uintptr_t)jumbo && address < (uintptr_t)jumbo+sizeof(jumbo)) return SBA0_JBO;
 return 0;
}
static struct sk_buff *alloc_skb(u32 length, gfp_t priority) {
 (void)priority;
 if (allocation_failure) return NULL;
 struct sk_buff *s = malloc(sizeof(*s)); assert(s);
 s->data = malloc(length); assert(s->data); s->capacity = length; allocated++;
 return s;
}
static void kfree_skb(struct sk_buff *s) { free(s->data); free(s); freed++; }
static int cbm_buffer_dma(u32 address, dma_addr_t *dma, u32 *base, u32 *capacity) {
 if (dma_failure) return -1;
 *base = address & ~(expected_capacity-1); *capacity = expected_capacity;
 *dma = (uintptr_t)expected_pool; return 0;
}
static void dma_sync_single_for_cpu(void *dev, dma_addr_t dma, u32 size, int direction) {
 (void)dev; (void)direction;
 assert(dma == (uintptr_t)expected_pool && size == expected_capacity);
 assert(!returned); synced++;
}
static int raw_smp_processor_id(void) { return 0; }
static int cbm_buffer_free_grx500(u32 cpu, void *data, u32 flags) {
 (void)cpu; (void)flags;
 assert(data == expected_pool && synced == 1 && returned == 0);
 returned++; return 0;
}
HELPER
static void reset(void) {
 allocation_failure = dma_failure = allocated = freed = synced = returned = 0;
}
int main(void) {
 unsigned cases = 0;
 assert((uintptr_t)standard <= UINT32_MAX && (uintptr_t)jumbo <= UINT32_MAX);
 for (unsigned pool=0; pool<2; pool++) {
  expected_pool = pool ? jumbo : standard;
  expected_capacity = pool ? sizeof(jumbo) : sizeof(standard);
  for (unsigned i=0; i<expected_capacity; i++) expected_pool[i]=(unsigned char)(i*37+pool);
  // Probe every possible payload boundary, including the formerly lost tail.
  for (u32 payload=1; payload<=expected_capacity+1; payload++) {
   reset();
   u32 length = SKB_DATA_ALIGN(payload);
   struct sk_buff *s=build_skb_grx500(expected_pool, length+SKB_DATA_ALIGN(sizeof(struct skb_shared_info)), 0);
   if (payload <= expected_capacity) {
    assert(s && s->capacity == length);
    assert(!memcmp(s->data, expected_pool, length));
    assert(allocated == 1 && freed == 0 && synced == 1 && returned == 1);
    kfree_skb(s);
   } else { assert(!s && !allocated && !synced && !returned); }
   cases++;
  }
  for (u32 length=0; length<=SKB_DATA_ALIGN(sizeof(struct skb_shared_info)); length++) {
   reset(); assert(!build_skb_grx500(expected_pool,length,0));
   assert(!allocated && !returned && !synced); cases++;
  }
  reset(); allocation_failure=1;
  assert(!build_skb_grx500(expected_pool,1024,0));
  assert(!allocated && !returned && !synced); cases++;
  reset(); dma_failure=1;
  assert(!build_skb_grx500(expected_pool,1024,0));
  assert(allocated==1 && freed==1 && !returned && !synced); cases++;
  reset(); assert(!build_skb_grx500(expected_pool+1,1024,0));
  assert(allocated==1 && freed==1 && !returned && !synced); cases++;
  reset(); assert(!build_skb_grx500(expected_pool,UINT32_MAX,0));
  assert(!allocated && !returned && !synced); cases++;
 }
 reset(); assert(!build_skb_grx500(NULL,1024,0));
 assert(!allocated && !returned && !synced); cases++;
 printf("%u CBM RX copy/ownership cases passed (ASan/UBSan; mocked DMA).\n",cases);
}
'''.replace('HELPER', helper).replace('JUMBO_SIZE', str(a.jumbo_size))
with tempfile.TemporaryDirectory(prefix='cbm-rx-test-') as directory:
    directory = Path(directory)
    (directory/'test.c').write_text(harness)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-pointer-to-int-cast', '-Wno-int-to-pointer-cast',
                    '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                    str(directory/'test.c'), '-o', str(directory/'test')], check=True)
    subprocess.run([str(directory/'test')], check=True)
