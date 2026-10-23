#!/usr/bin/env python3
"""Run the real upgrade shell against a fault-injectable, in-memory UBI model."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

PLATFORM = Path(__file__).resolve().parents[1] / 'base-files/lib/upgrade/platform.sh'
UPGRADE = Path(__file__).resolve().parents[4] / 'package/base-files/files/lib/upgrade'
MOCK = r'''#!/usr/bin/env python3
import hashlib,json,os,sys
from pathlib import Path
p=Path(os.environ['UBI_STATE']); s=json.loads(p.read_text())
cmd=Path(sys.argv[0]).name; a=sys.argv[1:]
s['calls'].append([cmd]+a)
def save(): p.write_text(json.dumps(s))
def fail(): save(); sys.exit(1)
def blocks(size): return (int(size)+s['leb']-1)//s['leb']
def free(): return s['capacity']-sum(blocks(v['size']) for v in s['volumes'].values())
if cmd==os.environ.get('FAIL_CMD'): fail()
if cmd=='fw_printenv': print(os.environ.get('BOOT_STATE','0'))
elif cmd=='find-ubi': print('ubi0' if s['attached'] else '')
elif cmd=='find-volume':
 v=s['volumes'].get(a[1]); print('ubi0_'+str(v['id']) if v else '')
elif cmd=='read-sysfs':
 attr=a[0].split('/')[-1]; obj=a[0].split('/')[-2]
 if attr=='eraseblock_size': print(s['leb'])
 elif attr=='avail_eraseblocks': print(free())
 elif attr=='reserved_ebs': print(blocks(next(v for v in s['volumes'].values() if v['id']==int(obj.split('_')[-1]))['size']))
 else: fail()
elif cmd=='grx500-check-ubi': pass
elif cmd=='ubiattach': s['attached']=True
elif cmd=='ubimkvol':
 name=a[a.index('-N')+1]; size=a[a.index('-s')+1]
 size=int(size[:-3])*1024*1024 if size.endswith('MiB') else int(size)
 if name in s['volumes'] or blocks(size)>free(): fail()
 s['next']+=1; s['volumes'][name]={'id':s['next'],'sha':'empty','size':size}
elif cmd=='ubirmvol':
 name=a[a.index('-N')+1]
 if name not in s['volumes']: fail()
 del s['volumes'][name]
elif cmd=='ubiupdatevol':
 vid=int(a[0].split('_')[-1]); v=next(v for v in s['volumes'].values() if v['id']==vid)
 if os.environ.get('FAIL_ROOT') and v is s['volumes'].get('openwrt-new-rootfs'): fail()
 data=sys.stdin.buffer.read(); length=int(a[a.index('-s')+1])
 if len(data)!=length: fail()
 v['sha']=hashlib.sha256(data).hexdigest()
elif cmd=='ubirename':
 pairs=list(zip(a[1::2],a[2::2])); old=s['volumes'].copy()
 if len({b for a,b in pairs})!=len(pairs) or any(a not in old for a,b in pairs): fail()
 for src,dst in pairs: s['volumes'].pop(src,None)
 for src,dst in pairs: s['volumes'][dst]=old[src]
elif cmd=='mount':
 if s.get('mounted'): fail()
 s['mounted']=int(a[-2].split('_')[-1])
elif cmd=='cp':
 if s.get('mounted') is None: fail()
 v=next(v for v in s['volumes'].values() if v['id']==s['mounted'])
 v['backup']=hashlib.sha256(Path(a[0]).read_bytes()).hexdigest()
 v['backup_name']=Path(a[1]).name
elif cmd=='umount': s['mounted']=None
elif cmd=='ubiblock': pass
else: raise RuntimeError(cmd)
save()
'''
HARNESS = r'''
. "$COMMON"
. "$NAND"
. "$PLATFORM"
board_name() { echo "${BOARD_NAME:-tplink,archer-ax3000-v1}"; }
find_mtd_index() {
 case "$1" in ubootconfigA) echo 1;; ubootconfigB) echo 2;; system_sw) echo 5;; esac
}
nand_find_ubi() { find-ubi; }
nand_find_volume() { find-volume "$@"; }
nand_remove_ubiblock() { ubiblock -r "/dev/$1"; }
cat() {
 case "$1" in
 /proc/cmdline) printf '%s\n' "$BOOT_CMDLINE";;
 /sys/class/mtd/mtd1/offset) echo "${MTD_A_OFFSET:-1048576}";;
 /sys/class/mtd/mtd2/offset) echo "${MTD_B_OFFSET:-1310720}";;
 /sys/class/mtd/mtd[12]/size) echo "${MTD_ENV_SIZE:-262144}";;
 /sys/class/mtd/mtd[12]/erasesize) echo "${MTD_ENV_ERASESIZE:-131072}";;
 /sys/class/mtd/mtd[12]/writesize) echo "${MTD_ENV_WRITESIZE:-2048}";;
 /sys/class/mtd/mtd[12]/type) echo "${MTD_ENV_TYPE:-nand}";;
 /sys/class/mtd/mtd5/size) echo "${NAND_SIZE:-130023424}";;
 /sys/class/ubi/*) read-sysfs "$1";;
 *) command cat "$@";; esac
}
sync() { :; }
mkdir() { :; }
if [ "$CHECK_ONLY" = 1 ]; then platform_check_image "$IMAGE"; else grx500_upgrade_tar "$IMAGE"; fi
'''

class UpgradeTests(unittest.TestCase):
    def run_case(self, **extra):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); bindir=root/'bin'; bindir.mkdir()
            mock=bindir/'mock'; mock.write_text(MOCK); mock.chmod(0o755)
            for cmd in ['fw_printenv','find-ubi','find-volume','grx500-check-ubi','ubiattach','ubimkvol','ubirmvol','ubiupdatevol','ubirename','ubiblock','read-sysfs','mount','umount','cp']:
                (bindir/cmd).symlink_to(mock)
            names=['kernelA','rootfsA','kernelB','rootfsB','bootcoreA','bootcoreB','firmwareA','firmwareB','sysconfig','rootfs_data']
            initial={name:{'id':i,'sha':'original-'+name,'size':1000} for i,name in enumerate(names)}
            stale=extra.pop('STALE',False)
            if stale:
                initial['openwrt-backup-rootfs']={'id':19,'sha':'old-backup','size':8388608}
            capacity=extra.pop('CAPACITY',1024)
            malformed=extra.pop('MALFORMED','')
            backup=extra.pop('BACKUP',False)
            nand=root/'nand.sh'; nand.write_text((UPGRADE/'nand.sh').read_text().replace('. /lib/functions.sh',''))
            backup_file=root/'backup.tgz'; backup_file.write_bytes(b'configuration backup')
            if extra.pop('MISSING_CORE',False): del initial['bootcoreA']
            if extra.pop('NO_DATA',False): del initial['rootfs_data']
            state=root/'state.json'; state.write_text(json.dumps({'volumes':initial,'attached':False,'next':20,'calls':[],'capacity':capacity,'leb':126976}))
            kernel=(b'bad!' if malformed=='kernel_magic' else b'\x27\x05\x19\x56')+b'k'*8192
            filesystem=(b'bad!' if malformed=='root_magic' else b'hsqs')+b'r'*16384
            checksums=('kernel '+hashlib.sha256(kernel).hexdigest()+'\n'+
                       'root '+hashlib.sha256(filesystem).hexdigest()+'\n').encode()
            if malformed=='kernel_payload': kernel=kernel[:-1]+b'X'
            if malformed=='root_payload': filesystem=filesystem[:-1]+b'X'
            if malformed=='bad_sums_format': checksums=b'kernel invalid\nroot invalid\n'
            image=root/'sysupgrade.tar'
            with tarfile.open(image,'w') as tar:
                members=[('CONTROL',b'BOARD=tplink_archer-ax3000-v1\n'),('kernel',kernel),('root',filesystem),('SHA256SUMS',checksums)]
                if malformed=='duplicate': members.append(('kernel',kernel))
                if malformed=='duplicate_sums': members.append(('SHA256SUMS',checksums))
                if malformed=='missing_root': members=[item for item in members if item[0]!='root']
                if malformed=='missing_sums': members=[item for item in members if item[0]!='SHA256SUMS']
                if malformed=='missing_control': members=members[1:]
                for name,data in members:
                    info=tarfile.TarInfo('sysupgrade-tplink_archer-ax3000-v1/'+name); info.size=len(data)
                    tar.addfile(info,io.BytesIO(data))
            extra.setdefault('BOOT_CMDLINE', 'rootfsname=rootfs' + ('B' if extra.get('BOOT_STATE') == '2' else 'A'))
            env=dict(os.environ,COMMON=str(UPGRADE/'common.sh'),NAND=str(nand),UPGRADE_BACKUP=str(backup_file) if backup else '',PATH=str(bindir)+':'+os.environ['PATH'],PLATFORM=str(PLATFORM),IMAGE=str(image),UBI_STATE=str(state),**extra)
            shell=['bash','-c',HARNESS]
            if os.environ.get('GRX500_TEST_QEMU'):
                target=Path(os.environ['GRX500_TEST_ROOT'])
                shell=[os.environ['GRX500_TEST_QEMU'],'-L',str(target),
                       str(target/'bin/busybox'),'sh','-c',HARNESS]
            proc=subprocess.run(shell,env=env,capture_output=True,text=True)
            result=json.loads(state.read_text())
            return proc,initial,result,hashlib.sha256(kernel).hexdigest(),hashlib.sha256(filesystem).hexdigest()

    def test_atomic_commit_both_banks(self):
        for state,bank in [('0','A'),('2','B')]:
            with self.subTest(bank=bank):
                proc,old,new,k,r=self.run_case(BOOT_STATE=state)
                self.assertEqual(proc.returncode,0,proc.stderr)
                self.assertEqual(new['volumes']['kernel'+bank]['sha'],k)
                self.assertEqual(new['volumes']['rootfs'+bank]['sha'],r)
                self.assertEqual(new['volumes']['openwrt-backup-kernel'],old['kernel'+bank])
                self.assertEqual(new['volumes']['openwrt-backup-rootfs'],old['rootfs'+bank])
                self.assertEqual(new['volumes']['openwrt-backup-data'],old['rootfs_data'])
                for name in old.keys()-{'kernel'+bank,'rootfs'+bank,'rootfs_data'}:
                    self.assertEqual(new['volumes'][name],old[name])
                self.assertEqual(sum(c[0]=='ubirename' for c in new['calls']),1)

    def test_trial_or_ambiguous_bank_never_writes(self):
        for state,cmdline in [('0','rootfsname=rootfsB'), ('2','rootfsname=rootfsA'),
                              ('0',''), ('0','rootfsname=rootfsA rootfsname=rootfsA'),
                              ('0','rootfsname=rootfsA rootfsname=rootfsB'),
                              ('0','rootfsname=rootfsAX'), ('0','xrootfsname=rootfsA')]:
            with self.subTest(state=state,cmdline=cmdline):
                proc,old,new,_,_=self.run_case(BOOT_STATE=state,BOOT_CMDLINE=cmdline)
                self.assertNotEqual(proc.returncode,0)
                self.assertEqual(new['volumes'],old)
                self.assertTrue(all(c[0]=='fw_printenv' for c in new['calls']))

    def test_boot_environment_geometry_must_match_stock(self):
        for setting,value in [('MTD_A_OFFSET','1'),('MTD_B_OFFSET','1'),
                              ('MTD_ENV_SIZE','1'),('MTD_ENV_ERASESIZE','1'),
                              ('MTD_ENV_WRITESIZE','1'),('MTD_ENV_TYPE','nor')]:
            with self.subTest(setting=setting):
                proc,old,new,_,_=self.run_case(**{setting:value})
                self.assertNotEqual(proc.returncode,0)
                self.assertIn('boot environment partition geometry',proc.stderr)
                self.assertEqual(new['volumes'],old)
                self.assertEqual(new['calls'],[])

    def test_faults_preserve_active_and_other_volumes(self):
        for failure in [{'FAIL_ROOT':'1'},{'FAIL_CMD':'ubimkvol'},{'FAIL_CMD':'ubirename'},
                        {'FAIL_CMD':'fw_printenv'},{'FAIL_CMD':'ubiattach'},
                        {'FAIL_CMD':'grx500-check-ubi'},
                        {'BOOT_STATE':'1'},{'BOOT_STATE':'3'},{'BOOT_STATE':'junk'},
                        {'NAND_SIZE':'1'},{'MISSING_CORE':True}]:
            with self.subTest(failure=failure):
                proc,old,new,_,_=self.run_case(**failure)
                self.assertNotEqual(proc.returncode,0)
                for name,value in old.items():
                    self.assertEqual(new['volumes'][name],value)
                self.assertFalse(any(c[0] in ['ubiformat','nandwrite','fw_setenv'] for c in new['calls']))
                if failure.get('FAIL_CMD') == 'grx500-check-ubi':
                    self.assertFalse(any(c[0] == 'ubiattach' for c in new['calls']))


    def test_first_install_without_existing_overlay(self):
        proc,old,new,_,_=self.run_case(NO_DATA=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn('rootfs_data',new['volumes'])
        self.assertNotIn('openwrt-backup-data',new['volumes'])
        self.assertGreater(new['volumes']['kernelA']['id'],max(v['id'] for v in old.values()))
        self.assertGreater(new['volumes']['rootfsA']['id'],max(v['id'] for v in old.values()))

    def test_image_validation_before_writes(self):
        for failure in ['duplicate','missing_root','missing_sums','duplicate_sums',
                        'missing_control','kernel_magic','root_magic','kernel_payload',
                        'root_payload','bad_sums_format']:
            with self.subTest(failure=failure):
                proc,old,new,_,_=self.run_case(MALFORMED=failure)
                self.assertNotEqual(proc.returncode,0,proc.stdout)
                self.assertEqual(new['volumes'],old)
                self.assertFalse(any(c[0].startswith('ubi') for c in new['calls']))
        proc,old,new,_,_=self.run_case(BOARD_NAME='wrong,board')
        self.assertNotEqual(proc.returncode,0)
        self.assertEqual(new['volumes'],old)
        proc,_,new,_,_=self.run_case(CHECK_ONLY='1')
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertFalse(any(c[0].startswith('ubi') for c in new['calls']))

    def test_capacity_preflight_and_reclaim(self):
        # kernel/root need 1 LEB each; 8 MiB data needs 67, total 69.
        for capacity in [10,78]:
            proc,old,new,_,_=self.run_case(CAPACITY=capacity)
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('Insufficient UBI staging space',proc.stderr)
            self.assertEqual(new['volumes'],old)
            self.assertFalse(any(c[0] in ['ubimkvol','ubirmvol','ubiupdatevol','ubirename'] for c in new['calls']))
        proc,_,_,_,_=self.run_case(CAPACITY=79)
        self.assertEqual(proc.returncode,0,proc.stderr)
        # Old backup occupies 67 LEBs but can be reclaimed before allocation.
        proc,old,new,_,_=self.run_case(CAPACITY=79,STALE=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(new['volumes']['openwrt-backup-rootfs'],old['rootfsA'])
        # If even reclamation is insufficient, keep old backups as well.
        proc,old,new,_,_=self.run_case(CAPACITY=78,STALE=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertEqual(new['volumes'],old)

    def test_configuration_staged_before_commit(self):
        proc,_,new,_,_=self.run_case(BACKUP=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(new['volumes']['rootfs_data']['backup'],hashlib.sha256(b'configuration backup').hexdigest())
        self.assertEqual(new['volumes']['rootfs_data']['backup_name'],'sysupgrade.tgz')
        calls=[c[0] for c in new['calls']]
        self.assertLess(calls.index('umount'),calls.index('ubirename'))
        for cmd in ['mount','cp','umount']:
            with self.subTest(cmd=cmd):
                proc,old,new,_,_=self.run_case(BACKUP=True,FAIL_CMD=cmd)
                self.assertNotEqual(proc.returncode,0)
                for name,value in old.items(): self.assertEqual(new['volumes'][name],value)
                self.assertFalse(any(c[0]=='ubirename' for c in new['calls']))

    def test_ramfs_tools_and_metadata_required(self):
        source=PLATFORM.read_text()
        self.assertIn('RAMFS_COPY_BIN="mktemp ',source)
        self.assertIn('sha256sum',source)
        self.assertIn('REQUIRE_IMAGE_METADATA=1',source)

if __name__=='__main__': unittest.main()
