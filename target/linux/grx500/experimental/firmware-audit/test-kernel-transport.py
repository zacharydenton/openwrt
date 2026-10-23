#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check loader binding and rejection controls against the four actual builds."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from kernel_transport import decode_kernel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--relocated', type=Path, required=True)
    parser.add_argument('--cross-compile', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = []
    for variant in ('software', 'directconnect'):
        for kind in ('initramfs', 'sysupgrade'):
            name = variant + '-' + kind
            folder = args.relocated / ('relocated-' + name)
            image = (folder / 'kernel.uimage').read_bytes()
            original = (args.relocated / (name + '.uimage')).read_bytes()
            header = struct.unpack('>7I4B32s', image[:64])
            old_header = struct.unpack('>7I4B32s', original[:64])
            old, evidence = decode_kernel(old_header, original[64:], None, args.cross_compile)
            assert evidence['stock_flash_boot_compatible'] is False
            cases.append(dict(case=name + '-original-known-overlap', passed=True))
            raw, evidence = decode_kernel(header, image[64:], folder / 'loader.elf', args.cross_compile)
            assert raw == old
            cases.append(dict(case=name + '-wrapped-elf-binding', passed=True,
                              linux_sha256=hashlib.sha256(raw).hexdigest()))
            other = args.relocated / ('relocated-' + variant + '-' +
                                     ('sysupgrade' if kind == 'initramfs' else 'initramfs'))
            bad_header = list(header); bad_header[4] += 4
            for label, h, elf in (
                ('missing-loader', header, None),
                ('wrong-loader', header, other / 'loader.elf'),
                ('wrong-address', tuple(bad_header), folder / 'loader.elf'),
            ):
                try:
                    decode_kernel(h, image[64:], elf, args.cross_compile)
                except ValueError as error:
                    cases.append(dict(case=name + '-' + label, passed=True, rejection=str(error)))
                else:
                    raise AssertionError(name + '-' + label + ' was accepted')
    report = dict(passed=True, hardware_tested=False, cases=cases,
                  harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  helper_sha256=hashlib.sha256(Path(__file__).with_name('kernel_transport.py').read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'{len(cases)} kernel transport binding/rejection assertions passed')


if __name__ == '__main__':
    main()
