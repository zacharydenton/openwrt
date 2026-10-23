#!/usr/bin/env python3
"""Check actual CBM descriptor encoding and enqueue bounds, with DMA/MMIO stubs.

The optional MIPS compiler/runner execute the target's C bitfield layout.
Neither mode executes a device, kernel interrupt or actual DMA operation.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] /
               'files/drivers/net/ethernet/lantiq/cqm/grx500/cbm.c')
p.add_argument('--cc', default='gcc')
p.add_argument('--runner', type=Path)
p.add_argument('--output-dir', type=Path)
p.add_argument('--jumbo-size', type=int, choices=(8192, 16384), default=16384)
a = p.parse_args()
source = a.source.read_text()
header = (Path(__file__).resolve().parents[1] /
          'files/drivers/net/ethernet/lantiq/cqm/grx500/cbm.h').read_text()
layouts = re.findall(r'struct dma_desc \{.*?\n\};', header, re.S)
assert len(layouts) == 2

def function(name):
    match = re.search(r'^static int ' + name + r'\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]

harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint32_t dma_addr_t;
#define CBM_SUCCESS 0
#define CBM_FAILURE -1
#define CPU_EQM_PORT_NUM 4
#define SBA0_STD 1
#define SBA0_JBO 2
#define CBM_STD_BUF_SIZE 2048
#define CONFIG_CBM_JBO_PKT_SIZE JUMBO_SIZE
#define DMA_BIDIRECTIONAL 0
struct cbm_desc { u32 desc0, desc1, desc2, desc3; };
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#define CONFIG_LITTLE_ENDIAN 1
LITTLE_LAYOUT
#else
BIG_LAYOUT
#endif
/* Address tokens are not dereferenced. Pool geometry and DMA calls are mocks. */
static void *std_buf_base=(void *)0x10000000;
static void *jbo_buf_base=(void *)0x20000000;
static struct { void *dev; dma_addr_t dma_handle_std,dma_handle_jbo; }
    g_cbm_ctrl={NULL,0x01000000,0x02000000};
static unsigned synced, barriers, enqueued;
static u32 expected_dma, expected_size, expected_pointer, expected_pid;
static int check_ptr_valid_type(u32 addr) {
    if(addr>=0x10000000 && addr<0x10000800) return SBA0_STD;
    if(addr>=0x20000000 && addr<0x20000000+CONFIG_CBM_JBO_PKT_SIZE) return SBA0_JBO;
    return 0;
}
static void dma_sync_single_for_device(void *dev,dma_addr_t dma,u32 size,int direction) {
    (void)dev; assert(dma==expected_dma && size==expected_size);
    assert(direction==DMA_BIDIRECTIONAL && !synced && !barriers && !enqueued); synced++;
}
static void dma_wmb(void) { assert(synced==1 && !barriers && !enqueued); barriers++; }
static int cpu_enqueue_hw(u32 pid,struct cbm_desc *desc,void *pointer,int flags) {
    assert(synced==1 && barriers==1 && !enqueued && !flags);
    assert(pid==expected_pid && (uintptr_t)pointer==expected_pointer);
    assert(desc); enqueued++; return CBM_SUCCESS;
}
FUNCTIONS
static unsigned cases;
static void check(struct cbm_desc *desc,unsigned pid,int valid) {
    synced=barriers=enqueued=0; expected_pid=pid;
    int ret=cbm_cpu_enqueue(pid,desc);
    if((ret==CBM_SUCCESS)!=valid) {
        fprintf(stderr,"pid=%u pointer=%08x len=%u byte_offset=%u expected=%s got=%d\n",
                pid,desc?desc->desc2:0,desc?desc->desc3&0xffff:0,
                desc?(desc->desc3>>23)&7:0,valid?"accept":"reject",ret);
    }
    assert((ret==CBM_SUCCESS)==valid);
    assert(synced==(unsigned)valid && barriers==(unsigned)valid && enqueued==(unsigned)valid);
    cases++;
}
int main(void) {
    struct cbm_desc desc;
    assert(sizeof(struct dma_desc)==16);
    /* Fixed wire words for the target's big-endian descriptor layout. */
    assert(setup_desc(&desc,0x100000c2,1508,0x55667788,0x11223344)==CBM_SUCCESS);
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
    assert(desc.desc0==0x11223344 && desc.desc1==0x55667788);
#else
    assert(desc.desc0==0x55667788 && desc.desc1==0x11223344);
#endif
    assert(desc.desc2==0x100000c0 && desc.desc3==0x310005e4);
    cases++;
    for(unsigned pool=0;pool<2;pool++) {
        u32 base=pool?0x20000000:0x10000000;
        u32 size=pool?CONFIG_CBM_JBO_PKT_SIZE:2048;
        expected_dma=pool?0x02000000:0x01000000; expected_size=size;
        for(u32 pos=0;pos<size;pos+=8) for(u32 off=0;off<8;off++) {
            u32 remaining=size-pos-off;
            u32 lengths[]={remaining,remaining+1,0,60,1500,1518,4096,8192,65535};
            for(unsigned i=0;i<sizeof(lengths)/sizeof(lengths[0]);i++) {
                u32 len=lengths[i];
                assert(setup_desc(&desc,base+pos+off,len,0,0)==CBM_SUCCESS);
                assert(desc.desc2==base+pos && ((desc.desc3>>23)&7)==off);
                assert((desc.desc3&0xffff)==len);
                expected_pointer=expected_dma+pos;
                check(&desc,off%4,len<=remaining);
            }
        }
    }
    memset(&desc,0,sizeof(desc));
    check(NULL,0,0); check(&desc,0,0);
    desc.desc2=0x10000800; check(&desc,0,0);
    desc.desc2=0x20000000+CONFIG_CBM_JBO_PKT_SIZE; check(&desc,0,0);
    desc.desc2=0x10000000; check(&desc,4,0); check(&desc,UINT32_MAX,0);
    /* DMA descriptor addresses must be 8-byte aligned; offset is separate. */
    for(unsigned off=1;off<8;off++) { desc.desc2=0x10000000+off; check(&desc,0,0); }
    assert(setup_desc(NULL,0,1,0,0)==CBM_FAILURE); cases++;
    u32 oversized[]={65536,65537,UINT32_MAX};
    for(unsigned i=0;i<3;i++) {
        memset(&desc,0x5a,sizeof(desc)); struct cbm_desc old=desc;
        assert(setup_desc(&desc,0x10000000,oversized[i],0,0)==CBM_FAILURE);
        assert(!memcmp(&desc,&old,sizeof(desc))); cases++;
    }
    printf("PASS: %u CBM TX encoding/bounds cases (%s endian; mocked DMA/MMIO)\n",cases,
           __BYTE_ORDER__==__ORDER_BIG_ENDIAN__?"big":"little");
}
'''.replace('LITTLE_LAYOUT', layouts[0]).replace('BIG_LAYOUT', layouts[1])
harness = harness.replace('FUNCTIONS', '\n'.join(function(name) for name in
                         ('cbm_buffer_dma', 'setup_desc', 'cbm_cpu_enqueue')))
harness = harness.replace('JUMBO_SIZE', str(a.jumbo_size))

def run(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'probe.c').write_text(harness)
    flags = ['-std=gnu11', '-O1', '-g', '-fno-strict-aliasing']
    flags += ['-static'] if a.runner else ['-fno-pie', '-no-pie',
                                         '-fsanitize=address,undefined',
                                         '-fno-omit-frame-pointer']
    subprocess.run([a.cc, *flags, str(path / 'probe.c'), '-o', str(path / 'probe')], check=True)
    subprocess.run(([str(a.runner)] if a.runner else []) + [str(path / 'probe')],
                   cwd=path, check=True)

if a.output_dir:
    run(a.output_dir.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='cbm-tx-') as tmp:
        run(Path(tmp))
