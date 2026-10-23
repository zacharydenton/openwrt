#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build an experimental high-RAM decoder uImage, not a factory upload image."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import struct
import subprocess
import zlib

HERE = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unpack(data):
    if len(data) < 64:
        raise ValueError('truncated uImage')
    h = struct.unpack('>7I4B32s', data[:64])
    if h[0] != 0x27051956 or len(data) != 64 + h[3]:
        raise ValueError('uImage magic/size')
    if zlib.crc32(data[:4] + bytes(4) + data[8:64]) != h[1] or zlib.crc32(data[64:]) != h[6]:
        raise ValueError('uImage CRC')
    if h[4:6] != (0xa0020000, 0xa0020000) or h[7:11] != (5, 5, 2, 3):
        raise ValueError('requires the researched Linux/MIPS LZMA kernel layout')
    return h, data[64:]


def build(root, kernel, out):
    out.mkdir(parents=True, exist_ok=False)
    original = kernel.read_bytes()
    h, compressed = unpack(original)
    (out / 'original.uimage').write_bytes(original)
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    raw = decoder.decompress(compressed, max_length=0x03000000)
    if not decoder.eof or decoder.unused_data or not (0 < len(raw) <= 0x03000000 - 0x20000):
        raise ValueError('invalid, oversized or padded inner LZMA stream')
    compressed = compressed[:5] + len(raw).to_bytes(8, 'little') + compressed[13:]
    (out / 'payload.lzma').write_bytes(compressed)
    decoder_dir = root / 'target/linux/lantiq/image/lzma-loader/src'
    compilers = list((root / 'staging_dir').glob('toolchain-mips_24kc*/bin/mips-openwrt-linux-musl-gcc'))
    if len(compilers) != 1:
        raise ValueError('expected one prepared MIPS cross compiler')
    cc = str(compilers[0]); prefix = cc[:-3]
    build_env = dict(os.environ, STAGING_DIR=str(root / 'staging_dir'))
    flags = ['-Os', '-ffreestanding', '-fno-builtin', '-fno-pic', '-fno-pie',
             '-mno-abicalls', '-G0', '-mabi=32', '-march=mips32r2', '-msoft-float',
             '-fno-stack-protector', '-fno-asynchronous-unwind-tables', '-I', str(decoder_dir)]
    objects = []
    sources = [HERE / 'relocated-kernel.S', HERE / 'relocated-kernel.c', decoder_dir / 'LzmaDecode.c']
    for index, source in enumerate(sources):
        obj = out / f'part{index}.o'; objects.append(str(obj))
        subprocess.run([cc, *flags, '-c', str(source), '-o', str(obj)], check=True, env=build_env)
    subprocess.run([prefix + 'objcopy', '-I', 'binary', '-O', 'elf32-tradbigmips',
                    '-B', 'mips', '--rename-section', '.data=.payload,alloc,load,readonly,data,contents',
                    'payload.lzma', 'payload.o'], cwd=out, check=True)
    elf = out / 'loader.elf'; binary = out / 'loader.bin'
    subprocess.run([prefix + 'ld', '-static', '-T', str(HERE / 'relocated-kernel.lds'),
                    '-o', str(elf), *objects, str(out / 'payload.o')], check=True)
    subprocess.run([prefix + 'objcopy', '-O', 'binary', str(elf), str(binary)], check=True)
    loader = binary.read_bytes()
    outer = lzma.compress(loader, format=lzma.FORMAT_ALONE,
                         filters=[dict(id=lzma.FILTER_LZMA1, dict_size=1 << 23, lc=3, lp=0, pb=2)])
    outer = outer[:5] + len(loader).to_bytes(8, 'little') + outer[13:]
    header = struct.pack('>7I4B32s', 0x27051956, 0, h[2], len(outer), 0xa4000000,
                         0xa4000000, zlib.crc32(outer), 5, 5, 2, 3,
                         b'OpenWrt AX3000 loader EXP')
    header = header[:4] + zlib.crc32(header).to_bytes(4, 'big') + header[8:]
    result = header + outer
    (out / 'kernel.uimage').write_bytes(result)
    report = dict(hardware_tested=False, factory_upload_image=False,
        original_kernel_sha256=sha(original), linux_expanded_sha256=sha(raw),
        linux_expanded_bytes=len(raw), inner_lzma_sha256=sha(compressed),
        loader_bytes=len(loader), loader_sha256=sha(loader), kernel_sha256=sha(result),
        stock_source='0x80800000', outer_destination='0xa4000000',
        inner_destination='0xa0020000', stack_top='0xa3ff0000',
        source_sha256={str(p):sha(p.read_bytes()) for p in sources +
                       [HERE / 'relocated-kernel.lds', HERE / 'build-relocated-kernel.py',
                        decoder_dir / 'LzmaDecode.h', decoder_dir / 'LzmaTypes.h']},
        limitations=['Uncached mapping and argument handoff require hardware confirmation.',
                     'Decoder tests do not establish a complete kernel boot.',
                     'This is a kernel transport experiment, not a complete installer.'])
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('openwrt', 'kernel', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.openwrt.resolve(), a.kernel.resolve(), a.output.resolve()), indent=2))
