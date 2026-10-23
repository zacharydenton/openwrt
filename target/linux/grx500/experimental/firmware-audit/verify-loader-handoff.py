#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check the bound, compiled AX3000 relocation-loader entry and ABI handoff.

This examines MIPS instructions; it does not execute the loader or kernel.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile


BASE = 0xa4000000
ENTRY = 0xa0020000
STACK = 0xa3ff0000
OUTPUT_END = 0xa3000000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(*cmd):
    return subprocess.check_output(cmd, text=True)


def symbols(nm):
    found = {}
    for line in nm.splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{8})\s+\S\s+(\S+)', line)
        if match:
            found[match[2]] = int(match[1], 16)
    for name in ('startup', 'grx500_decode', 'loader_main', 'payload_start',
                 'payload_end', 'probabilities', 'loader_end'):
        if name not in found:
            raise ValueError('missing loader symbol ' + name)
    return found


def word(raw, address):
    offset = address - BASE
    if offset < 0 or offset + 4 > len(raw):
        raise ValueError(f'instruction outside loaded bytes: {address:#x}')
    return struct.unpack_from('>I', raw, offset)[0]


def jump(address):
    return 0x0c000000 | ((address >> 2) & 0x03ffffff)


def check_startup(raw, sym):
    expected = [
        0x03a04025,  # move t0,sp: save U-Boot's stack
        0x3c1da3ff,  # lui sp,0xa3ff
        0x27bdffe0,  # reserve a 32-byte o32 frame
        0xafa80010,  # save old sp
        0xafbf0014,  # save U-Boot's return address
        jump(sym['loader_main']),
        0x00000000,  # jal delay slot
        0x8fbf0014,  # restore return address on failure
        0x8fbd0010,  # restore stack on failure
        0x03e00008,  # jr ra
        0x00000000,  # jr delay slot
    ]
    actual = [word(raw, BASE + index * 4) for index in range(len(expected))]
    if actual != expected:
        raise ValueError('compiled startup does not preserve the o32 boot ABI')
    return len(expected)


def check_handoff(raw, sym):
    start = sym['loader_main']
    end = sym['payload_start']
    insns = [word(raw, at) for at in range(start, end, 4)]
    decode_call = jump(sym['grx500_decode'])
    if insns.count(decode_call) != 1:
        raise ValueError('loader does not call the bound decoder exactly once')
    decode_at = insns.index(decode_call)
    for value in (0x00808025, 0x00a08825, 0x00c09025, 0x00e09825,
                  0x3c06a002, 0x3c0702fe):
        if value not in insns[:decode_at]:
            raise ValueError('missing saved boot argument, output address or limit')
    # After a successful decode the loader must order uncached output writes,
    # restore all four boot arguments and branch to the Linux entry. The a0
    # restoration occurs in jalr's delay slot.
    handoff = [0x0000000f, 0x3c02a002, 0x02603825, 0x02403025,
               0x02202825, 0x0040f809, 0x02002025]
    matches = [i for i in range(decode_at + 1, len(insns) - len(handoff) + 1)
               if insns[i:i + len(handoff)] == handoff]
    if len(matches) != 1:
        raise ValueError('compiled Linux argument/cache-order handoff differs')
    return start + matches[0] * 4


def find_bound_hash(report):
    matches = []
    def visit(value):
        if isinstance(value, dict):
            if 'loader_elf_sha256' in value:
                matches.append(value['loader_elf_sha256'])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(report)
    if len(matches) != 1 or not re.fullmatch(r'[0-9a-f]{64}', matches[0]):
        raise ValueError('image report has no unique bound loader ELF')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loader-elf', type=Path, required=True)
    parser.add_argument('--image-report', type=Path, required=True)
    parser.add_argument('--cross-compile', required=True)
    parser.add_argument('--negative-controls', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    elf = args.loader_elf.read_bytes()
    report = json.loads(args.image_report.read_text())
    if sha(elf) != find_bound_hash(report):
        raise ValueError('loader ELF does not match the verified image report')
    header = run(args.cross_compile + 'readelf', '-h', str(args.loader_elf))
    if not re.search(r'Entry point address:\s+0xa4000000\b', header):
        raise ValueError('loader ELF has wrong entry')
    relocations = run(args.cross_compile + 'readelf', '-r', str(args.loader_elf))
    if 'There are no relocations in this file.' not in relocations:
        raise ValueError('loader has unresolved relocations')
    sym = symbols(run(args.cross_compile + 'nm', '-n', str(args.loader_elf)))
    if not (sym['startup'] == BASE < sym['grx500_decode'] < sym['loader_main'] <
            sym['payload_start'] < sym['payload_end'] <= sym['probabilities'] <
            sym['loader_end'] < 0xa6000000):
        raise ValueError('loader symbol layout does not fit its memory region')
    if not (OUTPUT_END < STACK < BASE):
        raise ValueError('Linux output, stack and loader regions overlap')
    with tempfile.TemporaryDirectory(prefix='ax3000-loader-handoff-') as temp:
        binary = Path(temp) / 'loader.bin'
        subprocess.run([args.cross_compile + 'objcopy', '-O', 'binary',
                        str(args.loader_elf), str(binary)], check=True)
        raw = binary.read_bytes()
    if len(raw) != sym['payload_end'] - BASE:
        raise ValueError('loader binary has unexpected loaded range')
    startup_insns = check_startup(raw, sym)
    handoff_at = check_handoff(raw, sym)
    rejected = []
    if args.negative_controls:
        for name, address, check in [('startup', BASE, check_startup),
                                     ('handoff', handoff_at + 5 * 4, check_handoff)]:
            damaged = bytearray(raw)
            struct.pack_into('>I', damaged, address - BASE, 0)
            try:
                check(damaged, sym)
            except ValueError:
                rejected.append(name)
            else:
                raise ValueError('negative control was accepted: ' + name)
    result = {'passed': True, 'hardware_tested': False,
              'startup_assembly_executed': False, 'kernel_booted': False,
              'image_report_sha256': sha(args.image_report.read_bytes()),
              'loader_elf_sha256': sha(elf), 'loader_binary_sha256': sha(raw),
              'entry': hex(BASE), 'linux_entry': hex(ENTRY),
              'linux_output_end_limit': hex(OUTPUT_END), 'loader_stack': hex(STACK),
              'payload_start': hex(sym['payload_start']),
              'payload_end': hex(sym['payload_end']),
              'loader_end_including_bss': hex(sym['loader_end']),
              'startup_instructions_checked': startup_insns,
              'handoff_at': hex(handoff_at),
              'negative_controls_rejected': rejected,
              'limitations': ['Instruction/ABI inspection does not execute MIPS startup or prove cache state.',
                              'No physical boot, Ethernet, Wi-Fi, NAND or recovery is established.']}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: bound loader entry, stack, decoder call and four-argument Linux handoff')


if __name__ == '__main__':
    main()
