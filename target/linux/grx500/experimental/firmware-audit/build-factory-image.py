#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble an EXPERIMENTAL AX3000 US legacy factory container for laboratory tests.

The output is not a hardware-validated installation or recovery recommendation.
Requires an audit of the opt-in first-boot build; ordinary sysupgrade is refused.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tarfile
import zlib


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('stock','sysupgrade','audit','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    spec=importlib.util.spec_from_file_location('envelope',Path(__file__).with_name('test-stock-factory-envelope.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    stock=a.stock.read_bytes();audit=json.loads(a.audit.read_text())
    image_sha=module.sha(a.sysupgrade.read_bytes())
    if module.sha(stock)!=module.checker.STOCK_SHA:
        p.error('unresearched stock metadata')
    if not audit.get('checks_passed') or audit.get('image_sha256')!=image_sha:
        p.error('missing matching factory prerequisites audit')
    if a.output.exists():
        p.error('output already exists; retain prior candidates and their evidence')
    with tarfile.open(a.sysupgrade) as t:
        kernel=t.extractfile('sysupgrade-tplink_archer-ax3000-v1/kernel').read()
        root=t.extractfile('sysupgrade-tplink_archer-ax3000-v1/root').read()
    h=struct.unpack('>7I4B32s',kernel[:64])
    if h[4:6]!=(0xa4000000,0xa4000000) or h[7:11]!=(5,5,2,3):
        p.error('factory image requires relocated Linux kernel')
    if module.sha(kernel)!=audit['binding']['kernel_sha256'] or module.sha(root)!=audit['binding']['rootfs_sha256']:
        p.error('component audit binding mismatch')
    header=struct.pack('>7I4B32s',0x27051956,0,0,len(root),0,0,zlib.crc32(root),5,5,7,0,b'OpenWrt rootfs EXPERIMENTAL')
    header=header[:4]+zlib.crc32(header).to_bytes(4,'big')+header[8:]
    component=header+root
    body=component+bytes((-len(component))%16)+kernel
    candidate=module.envelope(stock[:module.COMPONENT_OFFSET]+body)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_bytes(candidate)
    report=dict(hardware_tested=False,upload_recommended=False,
        candidate_sha256=module.sha(candidate),candidate_bytes=len(candidate),
        sysupgrade_sha256=image_sha,kernel_sha256=module.sha(kernel),rootfs_sha256=module.sha(root),
        stock_sha256=module.sha(stock),audit_sha256=module.sha(a.audit.read_bytes()),
        components=['rootfs','kernel'],excluded_components=['uboot','bootcore','firmware','calibration'],
        limitations=['Stock writer parsing must be tested on these exact bytes.',
                    'Physical boot, flash writes, first-boot commitment and recovery are unverified.',
                    'Startup readiness checks do not establish Ethernet packet flow or wireless association.'])
    a.output.with_suffix(a.output.suffix+'.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
