#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bind an AX3000 sysupgrade archive to its kernel ELF and inspect its rootfs."""
import argparse
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile
import zlib
from kernel_transport import decode_kernel


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect(args):
    directory = 'sysupgrade-tplink_archer-ax3000-v1/'
    with tarfile.open(args.image) as archive:
        members = archive.getmembers()
        for name in ('kernel', 'root', 'SHA256SUMS'):
            match = [m for m in members if m.name == directory + name]
            if len(match) != 1 or not match[0].isfile() or not 0 < match[0].size < 64 << 20:
                raise ValueError('invalid or duplicate archive member: ' + name)
        kernel = archive.extractfile(directory + 'kernel').read()
        root = archive.extractfile(directory + 'root').read()
        checksums = archive.extractfile(directory + 'SHA256SUMS').read()
    expected_checksums = f'kernel {sha(kernel)}\nroot {sha(root)}\n'.encode()
    if checksums != expected_checksums:
        raise ValueError('kernel or rootfs SHA256SUMS mismatch')
    header = struct.unpack('>7I4B32s', kernel[:64])
    if header[0] != 0x27051956 or len(kernel) != header[3] + 64:
        raise ValueError('invalid uImage length or magic')
    if zlib.crc32(kernel[:4] + bytes(4) + kernel[8:64]) != header[1] or \
       zlib.crc32(kernel[64:]) != header[6]:
        raise ValueError('uImage CRC mismatch')
    if header[7:11] != (5, 5, 2, 3):
        raise ValueError('unexpected boot address, architecture or compression')
    raw, transport = decode_kernel(header, kernel[64:], args.loader_elf, args.cross_compile)
    if root[:4] != b'hsqs':
        raise ValueError('root is not squashfs')
    with tempfile.TemporaryDirectory(prefix='ax3000-sysupgrade-') as temp:
        temp = Path(temp)
        binary, squashfs, metadata = temp/'kernel.bin', temp/'root', temp/'metadata.json'
        command = [args.cross_compile + 'objcopy', '-O', 'binary', '-S']
        for section in ('.reginfo', '.notes', '.note', '.comment', '.mdebug', '.note.gnu.build-id'):
            command += ['-R', section]
        subprocess.run(command + [str(args.elf), str(binary)], check=True)
        elf_bytes = binary.read_bytes()
        if raw[:len(elf_bytes)] != elf_bytes:
            raise ValueError('supplied ELF does not reproduce sysupgrade kernel')
        dtb = raw[len(elf_bytes):]
        if len(dtb) < 8 or struct.unpack('>II', dtb[:8]) != (0xd00dfeed, len(dtb)):
            raise ValueError('missing or malformed appended DTB')
        spec = importlib.util.spec_from_file_location(
            'clock_audit', Path(__file__).with_name('clock-audit.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        clock_evidence = module.audit_clocks(dtb, Path(__file__).resolve().parents[2])
        module.audit_compiled_clocks(clock_evidence, elf_bytes, args.elf, args.cross_compile)
        subprocess.run([args.fwtool, '-i', str(metadata), str(args.image)], check=True)
        meta = json.loads(metadata.read_text())
        if meta['supported_devices'] != ['tplink,archer-ax3000-v1'] or \
           meta['version']['target'] != 'grx500/generic':
            raise ValueError('wrong image metadata')
        squashfs.write_bytes(root)
        checked = {}
        for path in ('lib/upgrade/platform.sh', 'etc/board.d/02_network',
                     'lib/preinit/81_grx500_calibration', 'lib/preinit/82_grx500_factory_mac',
                     'usr/sbin/grx500-check-ubi', 'usr/sbin/wpad',
                     'lib/modules/6.18.55/mtlk.ko', 'lib/modules/6.18.55/mtlkroot.ko',
                     'etc/modules.d/60-iwlwav-stock',
                     'lib/firmware/ap_ram_gen6_wrx_600_real_phy.bin'):
            data = subprocess.check_output([args.unsquashfs, '-cat', str(squashfs), path])
            if not data:
                raise ValueError('missing rootfs ingredient: ' + path)
            if path == 'etc/modules.d/60-iwlwav-stock' and b'fastpath=0,0,0' not in data:
                raise ValueError('software Wi-Fi datapath default changed')
            checked[path] = sha(data)
        upgrade_source = Path(__file__).resolve().parents[2] / 'base-files/lib/upgrade/platform.sh'
        if checked['lib/upgrade/platform.sh'] != sha(upgrade_source.read_bytes()):
            raise ValueError('packaged upgrade policy differs from source')
        autoload_source = Path(__file__).resolve().parents[5] / 'package/kernel/iwlwav-stock/autoload'
        if checked['etc/modules.d/60-iwlwav-stock'] != sha(autoload_source.read_bytes()):
            raise ValueError('packaged Wi-Fi module parameters differ from source')
        if args.directconnect:
            for path in ('lib/modules/6.18.55/directconnect_datapath.ko',
                         'lib/modules/6.18.55/dc_mode-hw.ko',
                         'etc/modules.d/50-directconnect-grx500',
                         'etc/modules.d/60-iwlwav-stock'):
                data = subprocess.check_output([args.unsquashfs, '-cat', str(squashfs), path])
                if not data:
                    raise ValueError('missing DirectConnect ingredient: ' + path)
                if path.endswith('60-iwlwav-stock') and b'fastpath=0,0,0' not in data:
                    raise ValueError('DirectConnect software default changed')
                checked[path] = sha(data)
    return dict(checks_passed=True,
                image_sha256=sha(args.image.read_bytes()), kernel_sha256=sha(kernel),
                payload_checksums_sha256=sha(checksums),
                rootfs_sha256=sha(root), dtb_sha256=sha(dtb), kernel_transport=transport,
                elf_sha256=sha(args.elf.read_bytes()), metadata=meta,
                rootfs_files=checked, clock_provider=clock_evidence, hardware_tested=False,
                limitation='Integrity and ingredient checks do not establish boot or flash compatibility.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('image', 'elf', 'output'):
        parser.add_argument('--' + option, type=Path, required=True)
    for option in ('cross-compile', 'fwtool', 'unsquashfs'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--directconnect', action='store_true')
    parser.add_argument('--loader-elf', type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args)
    except (ValueError, OSError, KeyError, struct.error, tarfile.TarError,
            subprocess.CalledProcessError, lzma.LZMAError) as error:
        parser.exit(1, str(error) + '\n')
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Sysupgrade integrity, metadata, ELF binding and rootfs checks passed.')


if __name__ == '__main__':
    main()
