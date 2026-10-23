#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pin the stock U-Boot boot-argument RAM layout to the compiled loader.

This checks exact big-endian MIPS words in the official 230831 raw bootloader.
It cannot observe the user's router or execute U-Boot.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


BASE = 0xa0400000
STOCK_SHA256 = '87fae41adc20ac4855d0716917cf4aaebec3c5688102360849fd43475a693f13'

# The init array invokes the DRAM function. That function stores initdram's
# return at gd+0x10. initdram selects one of two exact sizes. board_init_f
# places bi_boot_params in bd+0x0c, and bootm reads that same field.
WORDS = {
    0xa0400a70: 0x3c1c0005,  # GP = entry + 0x52990 = 0xa0453400
    0xa0400a74: 0x279c2990,
    0xa0400a78: 0x0399e021,
    0xa0400ab0: 0x8f9000b0,  # init array pointer from GP table
    0xa0400ab4: 0x8e190000,  # load each init function
    0xa0400ac0: 0x0320f809,  # call it
    0xa040076c: 0x3c1c0005,  # DRAM-function GP = 0xa0453400
    0xa0400770: 0x279c2c94,
    0xa0400774: 0x0399e021,
    0xa04007a0: 0x8f990050,  # initdram pointer from GP table
    0xa04007a4: 0x0320f809,  # call initdram
    0xa04007b0: 0xae020010,  # gd->ram_size = return value
    0xa041c98c: 0x3c040e00,  # 224 MiB choice
    0xa041c990: 0x3c030800,  # 128 MiB choice
    0xa041c994: 0x0082180b,  # movn: choose 224 MiB if probe nonzero
    0xa041c998: 0x00601021,  # return the selected size
    0xa0400ae4: 0x8f500010,  # read gd->ram_size
    0xa0400ae8: 0x3c048000,  # SDRAM base 0x80000000
    0xa0400aec: 0x02048021,
    0xa0400af0: 0x2403f000,  # align down to 4 KiB
    0xa0400af4: 0x02038024,
    0xa0400af8: 0x3c03fff8,  # reserve 0x80000
    0xa0400afc: 0x02038021,
    0xa0400b00: 0x3c12ffbf,  # board descriptor offset -0x400024
    0xa0400b04: 0x3c03ffff,  # align down to 64 KiB
    0xa0400b0c: 0x02038024,
    0xa0400b10: 0x3652ffdc,
    0xa0400b08: 0x3c11ffbb,  # bi_boot_params offset -0x440048
    0xa0400b14: 0x3631ffb8,
    0xa0400b18: 0x02121821,
    0xa0400b1c: 0x02112821,
    0xa0400b24: 0xaf430000,  # gd->bd = computed descriptor
    0xa0400b28: 0x02118821,
    0xa0400b2c: 0xac65000c,  # bd->bi_boot_params = computed pointer
    0xa0424168: 0x8f420000,  # bootm reads gd->bd
    0xa0424170: 0x8c52000c,  # bootm reads bi_boot_params
    0xa0424174: 0x3c02a000,  # convert pointer to KSEG1
    0xa042417c: 0x02429025,
}
POINTERS = {
    0xa04534b0: 0xa0452470,  # board_init_f init array
    0xa0452490: 0xa040076c,  # last init function: DRAM
    0xa0452494: 0,           # init-array terminator
    0xa0453450: 0xa041c964,  # initdram callee
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def word(data, address):
    offset = address - BASE
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f'address outside stock bootloader: {address:#x}')
    return struct.unpack_from('>I', data, offset)[0]


def check_words(data):
    for address, expected in {**WORDS, **POINTERS}.items():
        observed = word(data, address)
        if observed != expected:
            raise ValueError(f'stock U-Boot word {address:#x}: {observed:#x} != {expected:#x}')


def check_rea(path, sha256, procedure=None):
    raw = path.read_bytes()
    evidence = json.loads(raw)
    if evidence['subject']['digest']['sha256'] != sha256 or \
            evidence['subject']['architecture'] != 'mips_be':
        raise ValueError(f'REA Evidence does not identify the bootloader: {path}')
    profile = evidence['analysis_profile']['parameters']
    if profile['entry_point'] != hex(BASE) or \
            profile['language_id'] != 'MIPS:BE:32:default':
        raise ValueError(f'REA Evidence uses a different raw import: {path}')
    result = evidence['normalized_result']
    if procedure is None:
        if result['status'] != 'verified' or not all(c['matched'] for c in result['checks']):
            raise ValueError('REA load-image mapping is not fully verified')
    elif result['procedure']['address'] != hex(procedure):
        raise ValueError(f'REA function address differs: {path}')
    return {'path': str(path), 'sha256': digest(raw), 'evidence_id': evidence['evidence_id']}


def boot_param_addresses():
    values = []
    for mebibytes in (128, 224):
        ram_size = mebibytes << 20
        reserved_top = ((0x80000000 + ram_size) & 0xfffff000) - 0x80000
        reserved_top &= 0xffff0000
        cached = reserved_top - 0x440048
        uncached = (cached & 0x1fffffff) | 0xa0000000
        if uncached < 0xa6000000:
            raise ValueError('stock boot arguments can overlap the loader region')
        values.append({'ram_mib': mebibytes, 'cached': hex(cached),
                       'uncached': hex(uncached), 'physical': hex(cached & 0x1fffffff),
                       'margin_above_linux_output': uncached - 0xa3000000})
    return values


def check_loader(path):
    raw = path.read_bytes()
    report = json.loads(raw)
    if report['passed'] is not True or report['hardware_tested'] is not False:
        raise ValueError(f'loader report has unexpected scope: {path}')
    if report['linux_output_end_limit'] != '0xa3000000' or \
            report['loader_stack'] != '0xa3ff0000' or \
            not (0xa4000000 < int(report['loader_end_including_bss'], 16) < 0xa6000000):
        raise ValueError(f'loader memory range differs: {path}')
    return {'path': str(path), 'sha256': digest(raw),
            'loader_elf_sha256': report['loader_elf_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootloader', type=Path, required=True)
    parser.add_argument('--rea-load', type=Path, required=True)
    parser.add_argument('--rea-board-init', type=Path, required=True)
    parser.add_argument('--rea-initdram', type=Path, required=True)
    parser.add_argument('--rea-bootm', type=Path, required=True)
    parser.add_argument('--loader-report', type=Path, action='append', required=True)
    parser.add_argument('--negative-controls', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = args.bootloader.read_bytes()
    if digest(data) != STOCK_SHA256:
        raise ValueError('bootloader differs from the pinned official 230831 file')
    check_words(data)
    controls = []
    if args.negative_controls:
        for name, address in [('dram_size', 0xa041c990),
                              ('board_pointer', 0xa0400b2c),
                              ('bootm_pointer', 0xa0424170)]:
            damaged = bytearray(data)
            struct.pack_into('>I', damaged, address - BASE, 0)
            try:
                check_words(damaged)
            except ValueError:
                controls.append(name)
            else:
                raise ValueError('negative control escaped: ' + name)
    result = {
        'passed': True, 'hardware_tested': False,
        'stock_bootloader_sha256': STOCK_SHA256,
        'stock_bootloader_bytes': len(data),
        'raw_base': hex(BASE),
        'rea': {
            'load': check_rea(args.rea_load, STOCK_SHA256),
            'board_init': check_rea(args.rea_board_init, STOCK_SHA256, 0xa0400a70),
            'initdram': check_rea(args.rea_initdram, STOCK_SHA256, 0xa041c964),
            'bootm': check_rea(args.rea_bootm, STOCK_SHA256, 0xa04240f0),
        },
        'loader_reports': [check_loader(path) for path in args.loader_report],
        'ram_size_choices_mib': [128, 224],
        'boot_arguments': boot_param_addresses(),
        'mips_words_checked': len(WORDS),
        'data_pointers_checked': len(POINTERS),
        'negative_controls_rejected': controls,
        'limitations': [
            'The raw bootloader is from the official V1-family update, not the user router.',
            'Exact instruction matching and REA decompilation do not execute U-Boot or Linux.',
            'REA board-init pseudocode exceeds its reported FunctionManager body; exact words establish this path.',
            'This proves only boot-argument region separation for the two encoded RAM-size choices.',
        ],
    }
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: stock U-Boot argument block lies above the Linux output and loader')


if __name__ == '__main__':
    main()
