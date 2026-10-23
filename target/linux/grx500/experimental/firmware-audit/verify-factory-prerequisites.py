#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bind first-boot prerequisites to the actual factory kernel and rootfs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('image', 'elf', 'loader-elf', 'openwrt', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    a.openwrt = a.openwrt.resolve()
    cross = str(next((a.openwrt/'staging_dir').glob('toolchain-mips_24kc*/bin/mips-openwrt-linux-musl-gcc')))[:-3]
    with tempfile.TemporaryDirectory(prefix='ax3000-factory-audit-') as temp:
        temp = Path(temp)
        command = ['python3', str(Path(__file__).with_name('verify-sysupgrade.py')),
                   '--image', str(a.image), '--elf', str(a.elf), '--loader-elf', str(a.loader_elf),
                   '--cross-compile', cross, '--fwtool', str(a.openwrt/'staging_dir/host/bin/fwtool'),
                   '--unsquashfs', str(a.openwrt/'staging_dir/host/bin/unsquashfs4'),
                   '--output', str(temp/'binding.json')]
        subprocess.run(command, check=True)
        binding = json.loads((temp/'binding.json').read_text())
        with tarfile.open(a.image) as archive:
            root = archive.extractfile('sysupgrade-tplink_archer-ax3000-v1/root').read()
        (temp/'root').write_bytes(root)
        checked = {}
        for name in ('etc/grx500-factory-install', 'etc/grx500-boot-contract',
                     'lib/upgrade/platform.sh',
                     'lib/functions/grx500-trial.sh', 'lib/preinit/79_grx500_trial',
                     'usr/libexec/grx500-trial', 'usr/sbin/grx500-trialctl',
                     'etc/init.d/grx500-trial',
                     'etc/rc.d/S98grx500-trial', 'usr/sbin/fw_setenv', 'usr/bin/jsonfilter'):
            data = subprocess.check_output([str(a.openwrt/'staging_dir/host/bin/unsquashfs4'),
                                            '-cat', str(temp/'root'), name])
            if name != 'etc/grx500-factory-install' and not data:
                raise ValueError('empty prerequisite: ' + name)
            checked[name] = sha(data)
            source = a.openwrt/'target/linux/grx500/base-files'/name
            if name == 'usr/sbin/grx500-trialctl':
                source = a.openwrt/'package/utils/grx500-factory/files/grx500-trialctl'
            if source.is_file() and source.read_bytes() != data:
                raise ValueError('rootfs prerequisite differs from source: ' + name)
        # The worker checks ownership/mode and holds two locks. Bind all three
        # target applets, rather than relying on the host test shell's PATH.
        for applet in ('flock', 'find', 'id'):
            name = 'usr/bin/' + applet
            listing = subprocess.check_output([str(a.openwrt/'staging_dir/host/bin/unsquashfs4'),
                                               '-ll', str(temp/'root'), name], text=True)
            if 'squashfs-root/' + name + ' -> ../../bin/busybox' not in listing:
                raise ValueError('factory rootfs is missing the BusyBox ' + applet + ' applet link')
            checked[name] = sha(b'../../bin/busybox')
        # The preceding audit binds this ELF to the inner Linux image.
        binary = temp/'linux.bin'
        subprocess.run([cross+'objcopy', '-O', 'binary', '-S', '-R', '.reginfo',
                        '-R', '.notes', '-R', '.note', '-R', '.comment', '-R', '.mdebug',
                        '-R', '.note.gnu.build-id', str(a.elf), str(binary)], check=True)
        raw = binary.read_bytes()
        symbols = {}
        for line in subprocess.check_output([cross+'nm', '-S', '-n', str(a.elf)], text=True).splitlines():
            parts = line.split()
            if len(parts) == 4:
                symbols[parts[3]] = (int(parts[0],16), int(parts[1],16))
            elif len(parts) == 3:
                symbols[parts[2]] = (int(parts[0],16),0)
        base = symbols['_text'][0]
        address, length = symbols['grx500_partitions']
        # MIPS o32: 40-byte struct mtd_partition with size/offset at 8/16,
        # mask_flags/add_flags at 24/28. Assert size and every name/layout.
        assert length == 7*40, 'unexpected mtd_partition ABI'
        expected = [('uboot',0,0x100000,0x400),('ubootconfigA',0x100000,0x40000,0),
                    ('ubootconfigB',0x140000,0x40000,0),('gphyfirmware',0x180000,0x40000,0x400),
                    ('calibration',0x1c0000,0x100000,0x400),('system_sw',0x2c0000,0x7c00000,0),
                    ('res',0x7ec0000,0,0x400)]
        partitions=[]
        for i,(name,offset,size,mask) in enumerate(expected):
            pos=address-base+i*40
            pointer,types,sz,off,flags,added,node=struct.unpack('>IIQQIII',raw[pos:pos+36])
            actual=raw[pointer-base:].split(b'\0',1)[0].decode()
            assert (actual,off,sz,flags,types,added,node)==(name,offset,size,mask,0,0,0), name
            partitions.append(dict(name=name,offset=off,size=sz,mask_flags=flags))
    report=dict(checks_passed=True,hardware_tested=False,upload_recommended=False,
                image_sha256=sha(a.image.read_bytes()),binding=binding,
                first_boot_files=checked,compiled_partitions=partitions,
                limitation='Static prerequisite checks do not establish NAND writes, boot or network operation.')
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print('Factory first-boot files and compiled NAND permissions match the intended build')


if __name__ == '__main__':
    main()
