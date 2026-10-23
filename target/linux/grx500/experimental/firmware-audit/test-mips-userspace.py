#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise packaged AX3000 userland and real serializers under MIPS emulation.

Uses the actual sysupgrade SquashFS, target dynamic linker/libraries and BusyBox.
HE/UBI fixture executables are cross-compiled from the port's actual C sources.
No kernel, radio, NAND controller or network hardware is emulated here.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('openwrt', 'artifacts', 'qemu', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    for name in ('openwrt', 'artifacts', 'qemu', 'output'):
        setattr(a, name, getattr(a, name).resolve())
    here = Path(__file__).resolve().parent
    sandbox = load('stock_checker', here / 'test-stock-web-checker.py')
    factory = load('factory_fixture', here.parent / 'factory-mac/test-factory.py')
    cross = next((a.openwrt / 'staging_dir').glob('toolchain-mips_24kc_*/bin/mips-openwrt-linux-musl-gcc'))
    prepared = next((a.openwrt / 'build_dir/target-mips_24kc_musl/linux-grx500_generic').glob('iwlwav-stock-*'))
    he_test = a.openwrt / 'package/kernel/iwlwav-stock/tests/he-wire.c'
    he_header = prepared / 'wireless/driver/linux/wave_he_compat.h'
    ubi_source = a.openwrt / 'package/utils/grx500-factory/src/grx500-check-ubi.c'
    build_env = dict(os.environ, STAGING_DIR=str(a.openwrt / 'staging_dir/target-mips_24kc_musl'))
    a.output.mkdir(parents=True, exist_ok=True)
    results, images = [], {}
    with tempfile.TemporaryDirectory(prefix='ax3000-mips-') as temp:
        temp = Path(temp)
        work = temp / 'work'
        work.mkdir()
        subprocess.run([str(cross), '-static', '-Wall', '-Wextra', '-Werror',
                        '-I', str(he_header.parent), str(he_test), '-o', str(work / 'he-test')],
                       env=build_env, check=True)
        subprocess.run([str(cross), '-static', '-Wall', '-Wextra', '-Werror',
                        '-DGRX500_UBI_FIXTURE_TEST', str(ubi_source),
                        '-o', str(work / 'ubi-test')], env=build_env, check=True)
        fixture_elf_hashes = {n: sha((work / n).read_bytes()) for n in ('he-test', 'ubi-test')}
        for variant in ('software', 'directconnect'):
            image = a.artifacts / variant / 'images/openwrt-grx500-generic-tplink_archer-ax3000-v1-squashfs-sysupgrade.bin'
            squashfs = temp / (variant + '.squashfs')
            with tarfile.open(image) as archive:
                squashfs.write_bytes(archive.extractfile('sysupgrade-tplink_archer-ax3000-v1/root').read())
            root = temp / variant
            subprocess.run([str(a.openwrt / 'staging_dir/host/bin/unsquashfs4'), '-no-progress',
                            '-d', str(root), str(squashfs), 'bin', 'sbin', 'lib', 'usr', 'etc'],
                           check=True, stdout=subprocess.DEVNULL)
            images[variant] = dict(image_sha256=sha(image.read_bytes()),
                                   rootfs_sha256=sha(squashfs.read_bytes()),
                                   busybox_sha256=sha((root / 'bin/busybox').read_bytes()),
                                   factory_helper_sha256=sha((root / 'lib/functions/grx500-factory.sh').read_bytes()))
            prefix = sandbox.command(root, a.qemu, work)[:-5] + ['/qemu', '-strace']

            def run(name, argv, status=0, exact=None, contains=None):
                result = subprocess.run(prefix + argv, capture_output=True, text=True, timeout=15)
                passed = result.returncode == status
                if exact is not None:
                    passed &= result.stdout.strip() == exact
                if contains is not None:
                    passed &= contains in result.stdout + result.stderr
                stem = variant + '-' + name
                (a.output / (stem + '.stdout')).write_text(result.stdout)
                (a.output / (stem + '.strace')).write_text(result.stderr)
                results.append(dict(variant=variant, case=name, argv=argv,
                                    exit_code=result.returncode, expected_exit_code=status,
                                    passed=bool(passed), stdout_sha256=sha(result.stdout.encode()),
                                    strace_sha256=sha(result.stderr.encode())))
                print(('PASS' if passed else 'FAIL') + ': ' + stem)

            run('hostapd-loader', ['/usr/sbin/hostapd', '-v'], status=1, contains='hostapd v')
            run('iw-loader', ['/usr/sbin/iw', '--version'], contains='iw version')
            run('jshn-loader', ['/usr/bin/jshn', '-r', '{"band":"5g","up":true}'],
                contains="json_add_boolean 'up' 1;")
            run('fw-printenv-loader', ['/usr/sbin/fw_printenv', '--help'], contains='Print variables from U-Boot environment')
            run('he-wire', ['/work/he-test'], contains='HE firmware packing: 80/160/80+80, NSS, PPE bounds passed')
            # User-mode QEMU does not register a system-wide binfmt handler.
            # These shell functions route the packaged applets through /qemu.
            shell = ('wc() { /qemu /bin/busybox wc "$@"; }; '
                     'hexdump() { /qemu /bin/busybox hexdump "$@"; }; '
                     'awk() { /qemu /bin/busybox awk "$@"; }; '
                     '. /lib/functions/grx500-factory.sh; ')
            vectors = {
                'raw': (bytes.fromhex('10aabbccddfe'), '10:aa:bb:cc:dd:fe'),
                'text-dash': (b'MAC:10-AA-BB-CC-DD-FE\x00', '10:aa:bb:cc:dd:fe'),
                'text-colon': (b'MAC:10:aa:bb:cc:dd:fe\r\n', '10:aa:bb:cc:dd:fe'),
                'zero': (bytes(6), None),
                'multicast': (bytes.fromhex('11aabbccddfe'), None),
                'broadcast': (bytes.fromhex('ffffffffffff'), None),
                'shared-fallback': (bytes.fromhex('000aeb137b00'), None),
                'missing-prefix': (b'10:aa:bb:cc:dd:fe', None),
                'trailing-junk': (b'MAC:10:aa:bb:cc:dd:feMORE', None),
                'invalid-hex': (b'MAC:10:aa:bb:cc:dd:gg', None),
                'mixed-separator': (b'MAC:10-aa:bb:cc:dd:fe', None),
                'oversized': (b'MAC:10:aa:bb:cc:dd:fe' + bytes(512), None),
            }
            for name, (data, expected) in vectors.items():
                (work / 'input.bin').write_bytes(data)
                run('mac-' + name, ['/bin/busybox', 'sh', '-c', shell +
                    'grx500_factory_parse_mac /work/input.bin'],
                    status=0 if expected else 1, exact=expected if expected else '')
            for name, before, after in (
                ('increment', '10:aa:bb:cc:dd:fe', '10:aa:bb:cc:dd:ff'),
                ('carry', '10:aa:bb:cc:dd:ff', '10:aa:bb:cc:de:00'),
                ('oui-wrap', '10:aa:bb:ff:ff:ff', '10:aa:bb:00:00:00'),
            ):
                run('wan-' + name, ['/bin/busybox', 'sh', '-c', shell +
                    'grx500_factory_wan_mac ' + before], exact=after)
            valid = factory.container()
            bad_crc = bytearray(valid)
            bad_crc[12] ^= 1
            for name, data, status in (
                ('valid', valid, 0), ('blank', b'\xff' * 131072, 1),
                ('bad-crc', bad_crc, 1), ('no-data', factory.container(('kernelA', 'rootfsA')), 1),
                ('no-bank', factory.container(('data',)), 1),
            ):
                (work / 'input.bin').write_bytes(data)
                run('ubi-fixture-' + name, ['/work/ubi-test', '/work/input.bin'], status=status)
            run('installed-ubi-refuses-regular-file', ['/usr/sbin/grx500-check-ubi', '/work/input.bin'],
                status=1, contains='refusing attach')
    report = dict(hardware_tested=False, kernel_executed=False,
                  emulator_sha256=sha(a.qemu.read_bytes()), images=images, cases=results,
                  fixture_source_sha256={str(p): sha(p.read_bytes()) for p in (he_test, he_header, ubi_source)},
                  fixture_elf_sha256=fixture_elf_hashes, harness_sha256=sha(Path(__file__).read_bytes()),
                  passed=all(t['passed'] for t in results),
                  limitations=['Userspace ABI/serialization checks only; no GRX500 hardware model.',
                               'UBI fixture executables replace MTD ioctls with synthetic file geometry.',
                               'hostapd/iw version probes do not start radios or exercise nl80211.'])
    (a.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
