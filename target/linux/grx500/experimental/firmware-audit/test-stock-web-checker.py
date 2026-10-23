#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the exact stock upload checker in isolated MIPS user-mode emulation.

Only nvrammanager -c runs. No flash operation, server or router connection is
performed. Every candidate is a disposable writable copy because -c mmap-writes
its header temporarily and deletes rejected inputs. The shipped rootfs is read
only; network/PID namespaces, an ephemeral root and a minimal /dev isolate it.
This checks upload acceptance for one stock release, not firmware bootability.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

STOCK_SHA = '96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b'
CHECKER_SHA = '10eb5517fa1556bc5c6b716044b7b2b9c747bf9fe7a6f792d550bf22d771c342'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(rootfs, qemu, work, product_info=None):
    cmd = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
           '--cap-drop', 'ALL', '--clearenv', '--setenv', 'PATH',
           '/bin:/sbin:/usr/bin:/usr/sbin', '--tmpfs', '/']
    for name in ('bin', 'sbin', 'lib', 'usr', 'etc'):
        cmd += ['--ro-bind', str(rootfs / name), '/' + name]
    if product_info is not None:
        cmd += ['--ro-bind', str(product_info), '/etc/partition_config/product-info']
    return cmd + ['--ro-bind', str(qemu), '/qemu', '--proc', '/proc', '--dev', '/dev',
                  '--tmpfs', '/tmp', '--symlink', 'tmp', '/var', '--dir', '/data',
                  '--bind', str(work), '/work', '--chdir', '/work', '/qemu', '-strace',
                  '/usr/bin/nvrammanager', '-c', '/work/input.bin']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('rootfs', 'stock', 'qemu', 'artifacts', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    for name in ('rootfs', 'stock', 'qemu', 'artifacts', 'output'):
        setattr(a, name, getattr(a, name).resolve())
    stock = a.stock.read_bytes()
    checker = (a.rootfs / 'usr/bin/nvrammanager').read_bytes()
    if sha(stock) != STOCK_SHA or sha(checker) != CHECKER_SHA:
        p.error('stock image/checker differs from the researched release')
    if not shutil.which('bwrap'):
        p.error('bubblewrap is required; there is no unisolated fallback')
    a.output.mkdir(parents=True, exist_ok=True)
    product = (a.rootfs / 'etc/partition_config/product-info').read_bytes()
    corrupt_payload = bytearray(stock)
    corrupt_payload[-1] ^= 1
    corrupt_signature = bytearray(stock)
    corrupt_signature[0x130] ^= 1
    bad_length = bytearray(stock)
    bad_length[:4] = (len(stock) + 1).to_bytes(4, 'big')
    cases = [
        ('stock-valid', stock, None, True, 'chekc firmware file success!'),
        ('stock-payload-bitflip', corrupt_payload, None, False, 'Verify error!'),
        ('stock-signature-bitflip', corrupt_signature, None, False, 'Verify error!'),
        ('stock-bad-length', bad_length, None, False, "The file's length is bad"),
        ('stock-truncated', stock[:100], None, False, 'file size error!'),
        ('stock-wrong-model', stock, product.replace(b'product_name:Archer AX3000',
          b'product_name:Archer AX9999'), False, 'Firmwave not supports'),
        ('stock-wrong-region', stock, product.replace(b'special_id:55530000',
          b'special_id:45550000'), False, 'Firmwave not supports'),
        # The declared-length check permits bytes after the signed container.
        ('stock-trailing-bytes', stock + b'TEST TRAILING DATA', None, True,
         'chekc firmware file success!'),
    ]
    for variant in ('software', 'directconnect'):
        for kind in ('initramfs-kernel', 'squashfs-sysupgrade'):
            name = f'openwrt-grx500-generic-tplink_archer-ax3000-v1-{kind}.bin'
            image = a.artifacts / variant / 'images' / name
            cases.append((variant + '-' + kind, image.read_bytes(), None, False,
                          "The file's length is bad"))
    results = []
    for name, data, fixture, accepted, marker in cases:
        with tempfile.TemporaryDirectory(prefix='stock-check-') as tmp:
            work = Path(tmp)
            candidate = work / 'input.bin'
            candidate.write_bytes(data)
            product_path = None
            if fixture is not None:
                product_path = work / 'product-info'
                product_path.write_bytes(fixture)
            result = subprocess.run(command(a.rootfs, a.qemu, work, product_path),
                                    capture_output=True, text=True, timeout=30)
            (a.output / (name + '.stdout')).write_text(result.stdout)
            (a.output / (name + '.strace')).write_text(result.stderr)
            success = (result.returncode == 0) == accepted and marker in result.stdout
            # No MTD/UBI device is exposed, and -c must not attempt flash access.
            flash_access = any(s in result.stderr for s in ('"/dev/mtd', '"/dev/ubi'))
            success &= not flash_access
            if accepted:
                success &= candidate.exists() and candidate.read_bytes() == data
            entry = dict(case=name, input_sha256=sha(data), bytes=len(data),
                         expected_acceptance=accepted, exit_code=result.returncode,
                         expected_marker=marker, passed=bool(success),
                         flash_device_access_attempted=flash_access,
                         disposable_input_deleted=not candidate.exists(),
                         product_info_sha256=sha(fixture if fixture is not None else product),
                         stdout_sha256=sha(result.stdout.encode()),
                         strace_sha256=sha(result.stderr.encode()))
            results.append(entry)
            print(('PASS' if success else 'FAIL') + ': ' + name +
                  (' accepted' if result.returncode == 0 else ' rejected'))
    report = dict(stock_sha256=STOCK_SHA, checker_sha256=CHECKER_SHA,
                  qemu_sha256=sha(a.qemu.read_bytes()),
                  qemu_version=subprocess.check_output([str(a.qemu), '--version'], text=True).strip(),
                  harness_sha256=sha(Path(__file__).read_bytes()),
                  hardware_tested=False, flash_operations_performed=False,
                  stock_version='AX3000(US) 1.0.6 Build 20230831 rel.67466',
                  product_info_source='stock rootfs defaults; not read from the user device',
                  cases=results, passed=all(r['passed'] for r in results),
                  limitations=[
                      'Only the nvrammanager -c upload validation stage executes.',
                      'Web HTTP handling and the destructive -u writer are not executed.',
                      'Other stock firmware releases may use different checks.',
                      'Acceptance never establishes boot, RF, flash or recovery behavior.',
                  ])
    (a.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
