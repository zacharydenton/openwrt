#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce stock-address overlap and test experimental relocated decoding.

This is a vendor-decoder host memory model plus a real MIPS C decoder test.
It does not emulate GRX500, execute the startup assembly, or boot Linux.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('checker', HERE / 'test-stock-web-checker.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
sha = checker.sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('openwrt', 'bringup', 'uboot-src', 'relocated', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--factory-loader', type=Path, help='optional integrated factory sysupgrade loader directory')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    results = []
    source_hashes = {}
    with tempfile.TemporaryDirectory(prefix='boot-memory-') as tmp:
        work = Path(tmp)
        include = work / 'include'; (include / 'linux').mkdir(parents=True)
        (include / 'config.h').write_text('#define CONFIG_LZMA 1\n')
        (include / 'common.h').write_text('#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\n#define debug(...) ((void)0)\n')
        (include / 'watchdog.h').write_text('#define WATCHDOG_RESET() ((void)0)\n')
        (include / 'linux/string.h').write_text('#include <string.h>\n')
        vendor = a.uboot_src / 'lib/lzma'
        vendor_sources = [vendor / 'LzmaDec.c', vendor / 'LzmaTools.c']
        host = work / 'vendor-decoder'
        subprocess.run(['gcc', '-O2', '-I', str(include), '-I', str(a.uboot_src / 'include'),
                        '-I', str(vendor), str(HERE / 'boot-memory-probe.c'),
                        *map(str, vendor_sources), '-o', str(host)], check=True)
        for source in [*vendor_sources, vendor / 'LzmaDec.h', vendor / 'Types.h',
                       a.uboot_src / 'include/lzma/LzmaTypes.h']:
            source_hashes[str(source)] = sha(source.read_bytes())
        stock = (a.bringup / 'stock-230831.bin').read_bytes()
        if sha(stock) != checker.STOCK_SHA:
            p.error('unresearched stock firmware')
        cases = {'stock': stock[0x16f0f8f:]}
        for variant in ('software', 'directconnect'):
            images = a.bringup / 'artifacts' / variant / 'images'
            stem = 'openwrt-grx500-generic-tplink_archer-ax3000-v1-'
            cases[variant + '-initramfs'] = (images / (stem + 'initramfs-kernel.bin')).read_bytes()
            with tarfile.open(images / (stem + 'squashfs-sysupgrade.bin')) as t:
                cases[variant + '-sysupgrade'] = t.extractfile('sysupgrade-tplink_archer-ax3000-v1/kernel').read()
        if a.factory_loader:
            cases['factory-sysupgrade'] = (a.factory_loader / 'original.uimage').read_bytes()

        def host_case(name, data, source, destination, expected, should_match):
            image = work / 'input.uimage'; image.write_bytes(data)
            output = work / 'output.bin'; output.unlink(missing_ok=True)
            r = subprocess.run([str(host), str(image), hex(source), hex(destination), str(output)],
                               capture_output=True, text=True, timeout=45)
            matches = r.returncode == 0 and output.exists() and output.read_bytes() == expected
            entry = dict(case=name, mode='vendor-decoder-memory-model', exit_code=r.returncode,
                         source_offset=hex(source), destination_offset=hex(destination),
                         matches=matches, expected_match=should_match, passed=matches == should_match,
                         input_sha256=sha(data), expected_sha256=sha(expected),
                         decoder_status=r.stderr.strip())
            results.append(entry)
            print(('PASS' if entry['passed'] else 'FAIL') + ': ' + name, flush=True)

        for name, data in cases.items():
            dec = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
            expanded = dec.decompress(data[64:]); assert dec.eof
            host_case(name + '-stock-address', data, 0x800000, 0x20000, expanded, name == 'stock')
            host_case(name + '-ram-test-address', data, 0x4000000, 0x20000, expanded, True)

        decoder_dir = a.openwrt / 'target/linux/lantiq/image/lzma-loader/src'
        compilers = list((a.openwrt / 'staging_dir').glob('toolchain-mips_24kc*/bin/mips-openwrt-linux-musl-gcc'))
        assert len(compilers) == 1
        probe = work / 'probe'
        subprocess.run([str(compilers[0]), '-static', '-Os', '-DGRX500_DECODER_TEST',
                        '-I', str(decoder_dir), str(HERE / 'relocated-decoder-probe.c'),
                        str(HERE / 'relocated-kernel.c'), str(decoder_dir / 'LzmaDecode.c'),
                        '-o', str(probe)], check=True,
                       env=dict(os.environ, STAGING_DIR=str(a.openwrt / 'staging_dir')))
        qemu = a.bringup / 'web-upgrade-audit/usr/bin/qemu-mips-static'

        def mips_case(name, payload, expected, success):
            (work / 'payload.lzma').write_bytes(payload)
            decoded = work / 'decoded.bin'; decoded.unlink(missing_ok=True)
            cmd = checker.command(a.bringup / 'stock-rootfs', qemu, work)
            cmd[-3:] = ['/work/probe', '/work/payload.lzma', '/work/decoded.bin']
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            (a.output / (name + '.strace')).write_text(r.stderr)
            passed = (r.returncode == 0 and decoded.exists() and decoded.read_bytes() == expected) if success else r.returncode in range(1, 7) and not decoded.exists()
            results.append(dict(case=name, mode='MIPS-second-stage-decoder', passed=passed,
                                exit_code=r.returncode, input_sha256=sha(payload),
                                expected_sha256=sha(expected) if success else None,
                                strace_sha256=sha(r.stderr.encode())))
            print(('PASS' if passed else 'FAIL') + ': ' + name, flush=True)

        for name, original in cases.items():
            if name == 'stock':
                continue
            folder = a.factory_loader if name == 'factory-sysupgrade' else a.relocated / ('relocated-' + name)
            candidate = (folder / 'kernel.uimage').read_bytes()
            loader = (folder / 'loader.bin').read_bytes()
            host_case(name + '-relocated-outer', candidate, 0x800000, 0x4000000, loader, True)
            expected = lzma.decompress(original[64:], format=lzma.FORMAT_ALONE)
            payload = (folder / 'payload.lzma').read_bytes()
            mips_case(name + '-relocated-inner', payload, expected, True)
        for name, payload in [
            ('unknown-size', payload[:5] + b'\xff' * 8 + payload[13:]),
            ('oversize', payload[:5] + (0x04000000).to_bytes(8, 'little') + payload[13:]),
            ('bad-properties', b'\xff' + payload[1:]),
            ('truncated', payload[:32])]:
            mips_case(name, payload, None, False)

    report = dict(passed=all(c['passed'] for c in results), cases=results,
        hardware_tested=False, startup_assembly_executed=False, kernel_booted=False,
        stock_flash_address_original_images_compatible=False,
        source_sha256=source_hashes, harness_sha256=sha(Path(__file__).read_bytes()),
        limitations=['RAM offsets model cached/uncached aliasing; no GRX500 hardware is emulated.',
                     'The relocated decoder C executes under QEMU; startup assembly and kernel handoff do not.',
                     'No flash installation, bank commit, persistent overlay or recovery is established.'])
    (a.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
