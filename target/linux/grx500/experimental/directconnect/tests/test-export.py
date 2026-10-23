#!/usr/bin/env python3
"""Validate exported patches/integration against local source inputs, never a device."""
import argparse,pathlib,tempfile,tarfile,subprocess,hashlib,json,shutil
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--openwrt',required=True,type=pathlib.Path)
p.add_argument('--kernel',required=True,type=pathlib.Path)
p.add_argument('--wifi',required=True,type=pathlib.Path)
p.add_argument('--archive',required=True,type=pathlib.Path)
a=p.parse_args(); e=pathlib.Path(__file__).resolve().parents[1]
m=json.loads((e/'provenance.json').read_text())
assert hashlib.sha256(a.archive.read_bytes()).hexdigest()==m['directconnect']['archive_sha256']
def patch(cwd,path,dry=False):
 subprocess.run(['patch','--batch','-p1',*(['--dry-run'] if dry else []),'-i',str(path)],cwd=cwd,check=True,stdout=subprocess.DEVNULL)
patch(a.kernel,e/'170-grx500-directconnect.patch',True)
patch(a.wifi,e/'110-directconnect-wifi.patch',True)
with tempfile.TemporaryDirectory() as d:
 d=pathlib.Path(d)
 with tarfile.open(a.archive) as t:t.extractall(d,filter='data')
 source=d/('directconnect_dp-'+m['directconnect']['commit'])
 patch(source,e/'package/directconnect-grx500/patches/100-linux618-grx500.patch')
 assert 'dma_alloc_coherent' in (source/'dc_mode/dc_mode0/dc_mode0_xrx500.c').read_text()
 assert 'BIT(DP_CPU_LPID)' in (source/'dc_mode/dc_mode0/dc_mode0_xrx500.c').read_text()
 alternate=d/'openwrt'
 shutil.copytree(a.openwrt/'package/kernel/iwlwav-stock',alternate/'package/kernel/iwlwav-stock')
 shutil.copytree(a.openwrt/'target/linux/grx500',alternate/'target/linux/grx500')
 subprocess.run(['python3',str(e/'apply.py'),str(alternate)],check=True,stdout=subprocess.DEVNULL)
 original=a.openwrt/'package/kernel/iwlwav-stock/autoload'
 assert (alternate/'package/kernel/iwlwav-stock/autoload').read_bytes()==original.read_bytes()
 assert 'fastpath=0,0,0' in original.read_text()
 assert '+kmod-directconnect-grx500' in (alternate/'package/kernel/iwlwav-stock/Makefile').read_text()
 assert 'CONFIG_GRX500_UMT=y' in (alternate/'target/linux/grx500/config-6.18').read_text()
 print('PASS: pinned archive, kernel/Wi-Fi/source patches, alternate package integration, software default')
