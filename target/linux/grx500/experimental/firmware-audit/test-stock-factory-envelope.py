#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Test a prospective legacy factory envelope; NEVER emit an upload image.

Uses the pinned stock checker in QEMU. For writer parsing, replaces /bin/sh
with a host-native capture program: no real shell, vol_mgmt, flash or network.
Candidates and captured payloads exist only in disposable temporary directories.
This does not establish a usable or recoverable installation method.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('checker', HERE / 'test-stock-web-checker.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
sha = checker.sha
SALT = bytes.fromhex('7a2b15ed9b98596de504ab44ac2a9f4e')
COMPONENT_OFFSET = 0x1127


def envelope(data):
    data = bytearray(data)
    data[:4] = len(data).to_bytes(4, 'big')
    data[0x14:0x114] = b'fw-type:Legacy\n'.ljust(256, b'\0')
    data[4:20] = SALT
    data[4:20] = hashlib.md5(data[4:]).digest()
    return bytes(data)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('rootfs', 'stock', 'qemu', 'artifacts', 'output'):
        p.add_argument('--' + arg, type=Path, required=True)
    p.add_argument('--relocated', type=Path, help='optional directory of experimental relocated kernel builds')
    p.add_argument('--factory', type=Path, help='optional exact experimental factory candidate to capture')
    p.add_argument('--factory-sysupgrade', type=Path, help='sysupgrade archive supplying its exact expected components')
    a = p.parse_args()
    if bool(a.factory) != bool(a.factory_sysupgrade):
        p.error('--factory and --factory-sysupgrade must be supplied together')
    for key in vars(a):
        if getattr(a, key) is not None:
            setattr(a, key, getattr(a, key).resolve())
    stock = a.stock.read_bytes()
    binary = (a.rootfs / 'usr/bin/nvrammanager').read_bytes()
    if sha(stock) != checker.STOCK_SHA or sha(binary) != checker.CHECKER_SHA:
        p.error('unresearched stock image/checker')
    # Pinned ELF first LOAD: offset 0, virtual address 0x400000.
    if binary[0x106f4:0x10704] != SALT:
        p.error('unexpected legacy salt')
    a.output.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='factory-envelope-') as tmp:
        tmp = Path(tmp)
        capture = tmp / 'capture-shell'
        subprocess.run(['gcc', '-static', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(HERE / 'capture-upgrade-shell.c'), '-o', str(capture)], check=True)
        capture_sha = sha(capture.read_bytes())
        launcher = tmp / 'stock-ubus-launcher'
        subprocess.run(['gcc', '-static', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(HERE / 'stock-ubus-launcher.c'), '-o', str(launcher)], check=True)
        launcher_sha = sha(launcher.read_bytes())
        bin_fixture = tmp / 'bin'
        shutil.copytree(a.rootfs / 'bin', bin_fixture, symlinks=True)
        (bin_fixture / 'sh').unlink()
        shutil.copy2(capture, bin_fixture / 'sh')

        def run(name, data, marker, accept=True, writer=False, expected=None, product=None,
                with_ubus=False):
            with tempfile.TemporaryDirectory(prefix='case-', dir=tmp) as case:
                work = Path(case)
                (work / 'input.bin').write_bytes(data)
                fixture = None
                if product is not None:
                    fixture = work / 'product-info'
                    fixture.write_bytes(product)
                cmd = checker.command(a.rootfs, a.qemu, work, fixture)
                if writer:
                    # /bin/sh is a stock symlink; use a read-only /bin fixture
                    # containing the static capture executable in its place.
                    cmd[cmd.index(str(a.rootfs / 'bin'))] = str(bin_fixture)
                    cmd[-2] = '-u'
                if with_ubus:
                    i = cmd.index('--chdir')
                    cmd[i:i] = ['--ro-bind', str(launcher), '/launcher']
                    cmd[-5:] = ['/launcher']
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                (a.output / (name + '.stdout')).write_text(r.stdout)
                (a.output / (name + '.strace')).write_text(r.stderr)
                captured = {f.name.removeprefix('capture.'): f.read_bytes()
                            for f in work.glob('capture.*')}
                attempted = any(s in r.stderr for s in ('"/dev/mtd', '"/dev/ubi'))
                if with_ubus:
                    # Stock -u returns zero even for a component CRC failure;
                    # assert the outcome marker and captured bytes separately.
                    passed = (r.returncode == 0 and marker in r.stdout and not attempted
                              and 'pthread_cancel failed!' not in r.stdout
                              and 'Failed to connect to ubus' not in r.stderr)
                elif writer:
                    # The legacy pthread cancellation fails in this emulated
                    # environment AFTER parsing/capture. Assert that observed
                    # limitation explicitly; never report whole-updater success.
                    passed = (r.returncode == 255 and 'pthread_cancel failed!' in r.stdout
                              and marker in r.stdout and not attempted)
                else:
                    passed = ((r.returncode == 0) == accept and marker in r.stdout and not attempted)
                if expected is not None:
                    passed &= captured == expected
                calls = (work / 'calls.txt').read_text() if (work / 'calls.txt').exists() else ''
                results.append(dict(case=name, mode='writer-parser-capture' if writer else 'checker',
                    passed=bool(passed), exit_code=r.returncode, input_sha256=sha(data),
                    expected_exit_code=0 if with_ubus else (255 if writer or not accept else 0),
                    stock_ubusd_present=with_ubus,
                    updater_teardown_failed=writer and 'pthread_cancel failed!' in r.stdout,
                    input_bytes=len(data), flash_device_access_attempted=attempted,
                    captured={k: dict(bytes=len(v), sha256=sha(v)) for k, v in captured.items()},
                    captured_calls=calls, stdout_sha256=sha(r.stdout.encode()),
                    strace_sha256=sha(r.stderr.encode())))
                print(('PASS' if passed else 'FAIL') + ': ' + name, flush=True)

        valid = envelope(stock)
        run('legacy-stock', valid, 'chekc firmware file success!')
        bad = bytearray(valid)
        bad[-1] ^= 1
        run('legacy-bad-digest', bytes(bad), 'md5 verify error!', accept=False)
        # Rehashing a damaged uImage passes -c, demonstrating its coverage limit.
        run('legacy-damaged-uimage-checker', envelope(bad), 'chekc firmware file success!')
        product = (a.rootfs / 'etc/partition_config/product-info').read_bytes()
        run('legacy-wrong-region', valid, 'Firmwave not supports', accept=False,
            product=product.replace(b'special_id:55530000', b'special_id:45550000'))

        for variant in ('software', 'directconnect'):
            image = a.artifacts / variant / 'images' / 'openwrt-grx500-generic-tplink_archer-ax3000-v1-initramfs-kernel.bin'
            kernel = image.read_bytes()
            # Metadata stays byte-identical; this laboratory candidate has ONE
            # kernel component. No bootloader, rootfs, factory or bootcore update.
            data = envelope(stock[:COMPONENT_OFFSET] + kernel)
            run(variant + '-envelope-checker', data, 'chekc firmware file success!')
            run(variant + '-envelope-writer', data, 'upgradeFirmware success...',
                writer=True, expected={'kernel': kernel})
            damaged = bytearray(kernel)
            damaged[-1] ^= 1
            run(variant + '-bad-crc-writer', envelope(stock[:COMPONENT_OFFSET] + damaged),
                'Bad Header or Data Checksum', accept=False, writer=True, expected={})
            run(variant + '-writer-with-ubus', data, 'upgradeFirmware success...',
                writer=True, with_ubus=True, expected={'kernel': kernel})
            run(variant + '-bad-crc-with-ubus', envelope(stock[:COMPONENT_OFFSET] + damaged),
                'Bad Header or Data Checksum', accept=False, writer=True, with_ubus=True, expected={})

            if a.relocated is not None:
                for kind in ('initramfs', 'sysupgrade'):
                    folder = a.relocated / ('relocated-' + variant + '-' + kind)
                    relocated = (folder / 'kernel.uimage').read_bytes()
                    manifest = json.loads((folder / 'manifest.json').read_text())
                    if sha(relocated) != manifest['kernel_sha256']:
                        raise ValueError('relocated image identity mismatch')
                    body = relocated
                    expected = {'kernel': relocated}
                    if kind == 'sysupgrade':
                        archive = a.artifacts / variant / 'images' / 'openwrt-grx500-generic-tplink_archer-ax3000-v1-squashfs-sysupgrade.bin'
                        with tarfile.open(archive) as tar:
                            root = tar.extractfile('sysupgrade-tplink_archer-ax3000-v1/root').read()
                        header = struct.pack('>7I4B32s', 0x27051956, 0, 0, len(root), 0, 0,
                                             zlib.crc32(root), 5, 5, 7, 0, b'OpenWrt rootfs')
                        header = header[:4] + zlib.crc32(header).to_bytes(4, 'big') + header[8:]
                        component = header + root
                        body = component + bytes((-len(component)) % 16) + relocated
                        expected['rootfs'] = root
                    candidate = envelope(stock[:COMPONENT_OFFSET] + body)
                    name = variant + '-relocated-' + kind
                    run(name + '-checker', candidate, 'chekc firmware file success!')
                    run(name + '-writer', candidate, 'upgradeFirmware success...',
                        writer=True, with_ubus=True, expected=expected)

        if a.factory is not None:
            with tarfile.open(a.factory_sysupgrade) as t:
                expected = {name: t.extractfile('sysupgrade-tplink_archer-ax3000-v1/' + member).read()
                            for name, member in [('kernel', 'kernel'), ('rootfs', 'root')]}
            data = a.factory.read_bytes()
            run('exact-factory-checker', data, 'chekc firmware file success!')
            run('exact-factory-writer', data, 'upgradeFirmware success...', writer=True,
                with_ubus=True, expected=expected)
            labels = {line.split('\t', 2)[0]: line.split('\t', 2)[2]
                      for line in results[-1]['captured_calls'].splitlines()}
            labels_ok = labels == {'rootfs': 'OpenWrt rootfs EXPERIMENTAL',
                                   'kernel': 'OpenWrt AX3000 loader EXP'}
            results[-1]['component_labels_terminated'] = labels_ok
            results[-1]['passed'] &= labels_ok

    report = dict(passed=all(r['passed'] for r in results), cases=results,
        stock_sha256=sha(stock), checker_sha256=sha(binary), qemu_sha256=sha(a.qemu.read_bytes()),
        harness_sha256=sha(Path(__file__).read_bytes()), capture_binary_sha256=capture_sha,
        ubus_launcher_sha256=launcher_sha,
        ubus_launcher_source_sha256=sha((HERE / 'stock-ubus-launcher.c').read_bytes()),
        stock_ubusd_sha256=sha((a.rootfs / 'sbin/ubusd').read_bytes()),
        capture_source_sha256=sha((HERE / 'capture-upgrade-shell.c').read_bytes()),
        hardware_tested=False, flash_operations_performed=False, upload_image_emitted=False,
        limitations=['Writer child commands were captured, not executed.',
            'Without ubusd, the updater exits 255 at pthread_cancel; with the real stock service it exits zero.',
            'Even with ubusd, child flash/cleanup/reboot commands remain intercepted, not executed.',
            'No real vol_mgmt, bank switch, volume resize or boot was tested.',
            'Stock default product-info was used, not a readout from the user device.',
            'HTTP upload handler and rollback/recovery remain unverified.',
            'An accepted laboratory envelope is NOT a supported factory image.'])
    (a.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
