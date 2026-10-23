#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute packaged MIPS envtools on disposable redundant environment files.

Regular files use the same incremental flag scheme as NAND in fw_env.c.
This tests format, selection and batch editing, not NAND/ECC/power-loss behavior.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import zlib

SIZE = 0x4000


def make_env(flag, state):
    body = ('update_chk=' + state + '\0active_bank=A\0preserved=value with spaces\0\0').encode()
    body = body.ljust(SIZE - 5, b'\0')
    return zlib.crc32(body).to_bytes(4, 'big') + bytes([flag]) + body + b'\xff' * (0x40000 - SIZE)


def unpack(data):
    valid = int.from_bytes(data[:4], 'big') == zlib.crc32(data[5:SIZE])
    values = dict(x.decode().split('=', 1) for x in data[5:SIZE].split(b'\0') if x)
    return valid, data[4], values


def select(a, b):
    # U-Boot 2010.06 env_relocate_spec NAND redundancy algorithm, including wrap.
    av, af, _ = unpack(a); bv, bf, _ = unpack(b)
    if not av and not bv:
        return None
    if not av:
        return 1
    if not bv:
        return 0
    if af == 255 and bf == 0:
        return 1
    if bf == 255 and af == 0:
        return 0
    return 0 if af >= bf else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('rootfs', 'qemu', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('sandbox', Path(__file__).with_name('test-stock-web-checker.py'))
    sandbox = importlib.util.module_from_spec(spec); spec.loader.exec_module(sandbox)
    cases = []
    with tempfile.TemporaryDirectory(prefix='ax3000-env-') as temp:
        work = Path(temp)
        (work/'env.config').write_text('/work/envA 0 0x4000 0x20000 2\n/work/envB 0 0x4000 0x20000 2\n')
        (work/'batch').write_text('update_chk 2\nactive_bank B\n')
        prefix = sandbox.command(a.rootfs.resolve(), a.qemu.resolve(), work)[:-5] + ['--dir', '/tmp/lock', '/qemu', '-strace']
        for name, fa, fb, bad in [('a-newer', 5, 4, ''), ('b-newer', 4, 5, ''),
                ('equal', 5, 5, ''), ('wrap-to-a', 0, 255, ''), ('wrap-to-b', 255, 0, ''),
                ('commit-wrap', 255, 254, ''), ('bad-a', 6, 5, 'a'),
                ('bad-b', 5, 6, 'b'), ('both-invalid', 5, 6, 'ab')]:
            original = [make_env(fa, '0'), make_env(fb, '2')]
            for i, letter in enumerate('ab'):
                if letter in bad:
                    original[i] = bytes([original[i][0] ^ 1]) + original[i][1:]
                (work/('env' + letter.upper())).write_bytes(original[i])
            selected = select(*original)
            result = subprocess.run(prefix + ['/usr/sbin/fw_printenv', '-c', '/work/env.config', '-n', 'update_chk'], capture_output=True, text=True, timeout=15)
            (a.output/(name+'-read.strace')).write_text(result.stderr)
            if selected is None:
                assert result.returncode != 0, result.stdout
                assert [ (work/('env'+c)).read_bytes() for c in 'AB'] == original
                cases.append(dict(case=name, passed=True, writes_attempted=False)); continue
            assert result.returncode == 0 and result.stdout.strip() == unpack(original[selected])[2]['update_chk'], (result.stdout, result.stderr)
            result = subprocess.run(prefix + ['/usr/sbin/fw_setenv', '-c', '/work/env.config', '-s', '/work/batch'], capture_output=True, text=True, timeout=15)
            (a.output/(name+'-write.strace')).write_text(result.stderr)
            assert result.returncode == 0, result.stderr
            after = [(work/('env'+c)).read_bytes() for c in 'AB']
            assert after[selected] == original[selected], 'previous valid environment was modified'
            assert select(*after) == 1-selected
            valid, flag, values = unpack(after[1-selected])
            assert valid and flag == (unpack(original[selected])[1] + 1) % 256
            assert values == dict(unpack(original[selected])[2], update_chk='2', active_bank='B')
            cases.append(dict(case=name, passed=True, original_copy_preserved=True,
                              new_flag=flag, vendor_selector=1-selected))
    report = dict(passed=True, hardware_tested=False, cases=cases,
                  fw_env_sha256=hashlib.sha256((a.rootfs/'usr/sbin/fw_printenv').read_bytes()).hexdigest(),
                  harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  limitations=['Disposable regular files, not MTD devices.',
                               'No NAND bad-block, ECC or power-loss verification.',
                               'Vendor selector is a source-derived model, not stock bootloader execution.'])
    (a.output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'{len(cases)} MIPS redundant environment read/batch-edit cases passed')


if __name__ == '__main__':
    main()
