#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract the embedded kernel configuration from the pinned US 230831 update.

Offline evidence only: does not execute firmware or establish reset behavior.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zlib


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extract_config(kernel):
    marker = b'IKCFG_ST'
    if kernel.count(marker) != 1:
        raise ValueError('expected exactly one embedded configuration')
    start = kernel.index(marker) + len(marker)
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    config = decoder.decompress(kernel[start:], 2 * 1024 * 1024)
    if not decoder.eof or decoder.unconsumed_tail:
        raise ValueError('truncated or oversized embedded configuration')
    if not decoder.unused_data.startswith(b'IKCFG_ED'):
        raise ValueError('missing adjacent configuration end marker')
    end = len(kernel) - len(decoder.unused_data)
    settings = {}
    for line in config.decode('ascii').splitlines():
        match = re.fullmatch(r'(CONFIG_\w+)=(.+)', line)
        disabled = re.fullmatch(r'# (CONFIG_\w+) is not set', line)
        if match or disabled:
            name, value = match.groups() if match else (disabled[1], 'n')
            if name in settings:
                raise ValueError('duplicate configuration symbol: ' + name)
            settings[name] = value
    if settings.get('CONFIG_IKCONFIG') != 'y':
        raise ValueError('embedded configuration does not enable IKCONFIG')
    return config, settings, start, end


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        'extract_stock', Path(__file__).with_name('extract-stock.py'))
    stock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stock)
    firmware = args.firmware.read_bytes()
    if sha(firmware) != stock.SHA256:
        parser.error('input differs from researched AX3000 US 230831 update')
    if args.output_directory.exists():
        parser.error('output directory must not exist')
    payload, header = stock.uimage(firmware, 0x16f0f8f)
    kernel, tail = stock.decompress(payload)
    if any(tail):
        raise ValueError('nonzero kernel padding')
    config, settings, start, end = extract_config(kernel)
    selected = {name: value for name, value in settings.items()
                if any(word in name for word in
                       ('WATCHDOG', 'WDT', 'IKCONFIG', 'PANIC', 'LOCKUP',
                        'HUNG_TASK', 'KALLSYMS'))}
    report = {
        'schema': 1,
        'authority': 'CRC-checked static extraction from pinned stock update',
        'firmware_sha256': sha(firmware),
        'kernel_uimage': header,
        'kernel_sha256': sha(kernel),
        'config_sha256': sha(config),
        'config_bytes': len(config),
        'config_gzip_offset_in_kernel': hex(start),
        'config_gzip_end_in_kernel': hex(end),
        'config_gzip_crc_checked': True,
        'settings_count': len(settings),
        'selected_settings': selected,
        'hardware_tested': False,
        'upload_recommended': False,
        'limitations': [
            'Configuration identifies this downloaded kernel, not the running router.',
            'Disabled Linux watchdog support does not exclude independent bootcore or bootloader reset mechanisms.',
            'No reset, boot, networking, flash operation or fallback was executed.',
        ],
    }
    args.output_directory.mkdir(parents=True)
    (args.output_directory / 'stock-kernel.config').write_bytes(config)
    (args.output_directory / 'manifest.json').write_text(
        json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
