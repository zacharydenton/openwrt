# SPDX-License-Identifier: GPL-2.0-only
"""Bind the experimental transport to its ELF before inspecting inner Linux."""
import hashlib
import lzma
from pathlib import Path
import subprocess
import tempfile


def expand(data, limit):
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    raw = decoder.decompress(data, max_length=limit + 1)
    if not decoder.eof or decoder.unused_data or not 0 < len(raw) <= limit:
        raise ValueError('invalid, oversized or padded LZMA stream')
    return raw


def decode_kernel(header, payload, loader_elf, cross_compile):
    addresses = header[4:6]
    if addresses == (0xa0020000, 0xa0020000):
        if loader_elf:
            raise ValueError('loader ELF supplied for an unwrapped kernel')
        return expand(payload, 64 << 20), dict(
            kind='original-direct-lzma', stock_flash_boot_compatible=False,
            reason='Known source/output overlap at stock 0x80800000 load address')
    if addresses != (0xa4000000, 0xa4000000) or not loader_elf:
        raise ValueError('unknown boot addresses or missing --loader-elf')
    raw = expand(payload, 32 << 20)
    with tempfile.TemporaryDirectory(prefix='ax3000-loader-bind-') as directory:
        binary = Path(directory) / 'loader.bin'
        subprocess.run([cross_compile + 'objcopy', '-O', 'binary',
                        str(loader_elf), str(binary)], check=True, capture_output=True)
        if binary.read_bytes() != raw:
            raise ValueError('loader ELF does not reproduce outer decoded bytes')
    symbols = {}
    for line in subprocess.check_output(
            [cross_compile + 'nm', '-n', str(loader_elf)], text=True).splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols[parts[2]] = int(parts[0], 16)
    base = symbols['startup']
    start, end = symbols['payload_start'] - base, symbols['payload_end'] - base
    if base != 0xa4000000 or not 0 < start < end <= len(raw) or \
            not base + len(raw) <= symbols['loader_end'] < 0xa6000000:
        raise ValueError('loader symbols outside researched memory bounds')
    inner = raw[start:end]
    linux = expand(inner, 0x03000000 - 0x20000)
    if int.from_bytes(inner[5:13], 'little') != len(linux):
        raise ValueError('inner stream lacks exact decoded size')
    return linux, dict(kind='experimental-relocated-lzma',
        loader_elf_sha256=hashlib.sha256(loader_elf.read_bytes()).hexdigest(),
        loader_sha256=hashlib.sha256(raw).hexdigest(),
        inner_sha256=hashlib.sha256(inner).hexdigest(),
        outer_destination=hex(base), inner_destination='0xa0020000',
        hardware_tested=False,
        limitation='ELF binding and bounds do not execute startup or prove hardware boot')
