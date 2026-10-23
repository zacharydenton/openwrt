#!/usr/bin/env python3
"""Exercise factory MAC parsing and the installed C UBI guard on synthetic data."""
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib

BASE = Path(__file__).resolve().parents[2]
HELPER = BASE / 'base-files/lib/functions/grx500-factory.sh'
SOURCE = Path(__file__).parent / 'files/grx500-check-ubi.c'


def crc(data):
    return (zlib.crc32(data) ^ 0xffffffff) & 0xffffffff


def seal(data):
    data[-4:] = struct.pack('>I', crc(data[:-4]))
    return data


def table_record(name='', kind=1):
    out = bytearray(172)
    if name:
        struct.pack_into('>III', out, 0, 4, 1, 0)
        out[12] = kind
        struct.pack_into('>H', out, 14, len(name))
        out[16:16 + len(name)] = name.encode()
    return seal(out)


def container(names=('kernelA', 'rootfsA', 'data')):
    out = bytearray(b'\xff' * 131072)
    ec = bytearray(64)
    struct.pack_into('>I', ec, 0, 0x55424923)
    ec[4] = 1
    struct.pack_into('>II', ec, 16, 2048, 4096)
    out[:64] = seal(ec)
    vid = bytearray(64)
    struct.pack_into('>I', vid, 0, 0x55424921)
    vid[4:8] = bytes([1, 1, 0, 5])
    struct.pack_into('>I', vid, 8, 0x7fffefff)
    out[2048:2112] = seal(vid)
    for i in range(128):
        out[4096+i*172:4096+(i+1)*172] = table_record(names[i] if i < len(names) else '')
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--busybox', type=Path)
    args = parser.parse_args()
    checks = 0
    with tempfile.TemporaryDirectory(prefix='grx500-factory-test-') as temp:
        tmp = Path(temp)
        env = dict(os.environ)
        shell = ['/bin/sh']
        if args.busybox:
            shell = [str(args.busybox), 'sh']
            bindir = tmp / 'bin'
            bindir.mkdir()
            for applet in ('awk', 'wc', 'hexdump', 'tr'):
                (bindir / applet).symlink_to(args.busybox)
            env['PATH'] = str(bindir)
        vectors = {
            'raw': (bytes.fromhex('10aabbccddfe'), '10:aa:bb:cc:dd:fe'),
            'text-dash': (b'MAC:10-AA-BB-CC-DD-FE\x00', '10:aa:bb:cc:dd:fe'),
            'text-colon': (b'MAC:10:aa:bb:cc:dd:fe\r\n', '10:aa:bb:cc:dd:fe'),
            'zero': (bytes(6), None),
            'multicast': (bytes.fromhex('11aabbccddfe'), None),
            'broadcast': (bytes.fromhex('ffffffffffff'), None),
            'generic-fallback': (bytes.fromhex('000aeb137b00'), None),
            'missing-header': (b'10:aa:bb:cc:dd:fe', None),
            'trailing-junk': (b'MAC:10:aa:bb:cc:dd:feMORE', None),
            'bad-hex': (b'MAC:10:aa:bb:cc:dd:gg', None),
            'mixed-separator': (b'MAC:10-aa:bb:cc:dd:fe', None),
            'over-limit': (b'MAC:10:aa:bb:cc:dd:fe' + bytes(512), None),
        }
        for name, (contents, expected) in vectors.items():
            file = tmp / name
            file.write_bytes(contents)
            result = subprocess.run(shell + ['-c', '. "$1"; grx500_factory_parse_mac "$2"', 'test', str(HELPER), str(file)], env=env, text=True, capture_output=True)
            assert (result.returncode == 0) == (expected is not None), (name, result)
            if expected is not None:
                assert result.stdout.strip() == expected, (name, result.stdout)
            checks += 1
        for before, expected in [('10:aa:bb:cc:dd:fe', '10:aa:bb:cc:dd:ff'), ('10:aa:bb:cc:dd:ff', '10:aa:bb:cc:de:00'), ('10:aa:bb:ff:ff:ff', '10:aa:bb:00:00:00')]:
            result = subprocess.run(shell + ['-c', '. "$1"; grx500_factory_wan_mac "$2"', 'test', str(HELPER), before], env=env, check=True, text=True, capture_output=True)
            assert result.stdout.strip() == expected, result.stdout
            checks += 1
        binary = tmp / 'checker'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-DGRX500_UBI_FIXTURE_TEST', str(SOURCE), '-o', str(binary)], check=True)
        valid = container()
        cases = {'valid': (valid, True), 'blank': (b'\xff' * 131072, False), 'no-data': (container(('kernelA', 'rootfsA')), False), 'no-banks': (container(('data',)), False), 'short': (valid[:-1], False)}
        for name, offset in [('bad-ec-crc', 12), ('bad-vid-crc', 2056), ('bad-table-crc', 4100)]:
            bad = bytearray(valid)
            bad[offset] ^= 1
            cases[name] = (bad, False)
        # Data is not required to occupy the first physical eraseblock.
        cases['later-layout'] = (b'\xff' * 131072 + valid, True)
        for name, (contents, expected) in cases.items():
            file = tmp / ('ubi-' + name)
            file.write_bytes(contents)
            result = subprocess.run([str(binary), str(file)], capture_output=True)
            assert (result.returncode == 0) == expected, (name, result.stderr)
            checks += 1
        symlink = tmp / 'ubi-link'
        symlink.symlink_to(tmp / 'ubi-valid')
        assert subprocess.run([str(binary), str(symlink)], capture_output=True).returncode != 0
        checks += 1
    print(f'PASS: {checks} factory MAC/UBI fixtures' + (' (BusyBox shell/applets)' if args.busybox else ''))


if __name__ == '__main__':
    main()
