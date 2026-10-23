#!/usr/bin/env python3
"""Run the real first-boot shell in a private filesystem with mocked flash leaves."""
import json, os, re, subprocess, tempfile, unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]/'base-files'
TRIALCTL=Path(__file__).resolve().parents[4]/'package/utils/grx500-factory/files/grx500-trialctl'
MOCK=r'''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
p=Path('/work/state.json');s=json.loads(p.read_text());cmd=Path(sys.argv[0]).name;a=sys.argv[1:]
s['calls'].append([cmd]+a)
def save():p.write_text(json.dumps(s))
def fail():save();sys.exit(1)
if cmd==os.environ.get('FAIL_CMD'):fail()
if cmd=='fw_printenv':
 name=a[-1]
 if name not in s['env']:fail()
 print(s['env'][name])
elif cmd=='fw_setenv':
 if os.environ.get('PAUSE_COMMIT')=='1':
  Path('/work/commit-entered').touch()
  import time
  while not Path('/work/release-commit').exists():time.sleep(.01)
 for line in Path(a[a.index('-s')+1]).read_text().splitlines():
  k,v=line.split(' ',1);s['env'][k]=v
 if os.environ.get('BAD_READBACK'):s['env']['update_chk']='bad'
elif cmd=='find-volume':print(s['volumes'].get(a[1],''))
elif cmd=='ubimkvol':
 name=a[a.index('-N')+1]
 if name in s['volumes']:fail()
 s['volumes'][name]='ubi0_10'
elif cmd=='ubirename':
 if a[1] not in s['volumes'] or a[2] in s['volumes']:fail()
 s['volumes'][a[2]]=s['volumes'].pop(a[1])
elif cmd in ('mount','umount'):pass
elif cmd=='ubus':print('{"up":true}')
elif cmd=='jsonfilter':print('true')
elif cmd in ('iw','pidof'):pass
else:raise RuntimeError(cmd)
save()
'''
HARNESS=r'''
. /work/trial.sh
# The environment transaction is also exercised independently of manual acceptance.
# Only the test harness can substitute this predicate.
if [ "$MOCK_ACCEPTANCE" != 0 ]; then
 grx500_trial_acceptance() { return 0; }
fi
board_name() { echo "${BOARD:-tplink,archer-ax3000-v1}"; }
id() { [ "$1" = -u ] && echo "${TEST_UID:-0}"; }
find_mtd_index() { case "$1" in ubootconfigA) echo 1;; ubootconfigB) echo 2;; esac; }
grx500_factory_system_mtd() { echo 5; }
grx500_factory_parse_mac() { echo 10:aa:bb:cc:dd:fe; }
nand_find_ubi() { echo ubi0; }
nand_find_volume() { find-volume "$@"; }
sync() { :; }
reboot() { [ -f /tmp/grx500-trial-failed ] && touch /work/failed; touch /work/rebooted; }
GRX500_TRIAL_CONFIG=/work/env.config
[ "$MODE" != config ] || { grx500_trial_config; exit $?; }
[ "$NO_DECISION_LOCK" = 1 ] || mkdir -m 0700 /tmp/grx500-trial-lock
[ "$LOCK_SENTINEL" != 1 ] || printf 'retain\n' > /tmp/grx500-trial-lock/decision.lock
grx500_trial_prepare || exit 11
[ -f /tmp/grx500-trial-pending ] || exit 0
cp /tmp/grx500-trial-overlay/.ax3000-trial /overlay/.ax3000-trial
# Model the mount_root transition; no mount/rename ioctl is executed.
cp /work/mountinfo-after /proc/self/mountinfo
[ -z "$FAIL_HEALTH" ] || rm /sys/class/net/wan/health-placeholder
if [ "$FAIL_HEALTH" = 1 ]; then rm -r /sys/class/ieee80211/phy1; fi
case "$ACCEPT_MARKER" in
 valid) printf 'AX3000-US-V1-ACCEPT-1 %s %s\n' "$GRX500_TRIAL_BANK" "$(cat /proc/sys/kernel/random/boot_id)" > /tmp/grx500-trial-accept;;
 wrong_bank) printf 'AX3000-US-V1-ACCEPT-1 A %s\n' "$(cat /proc/sys/kernel/random/boot_id)" > /tmp/grx500-trial-accept;;
 stale_boot) printf 'AX3000-US-V1-ACCEPT-1 %s stale-boot\n' "$GRX500_TRIAL_BANK" > /tmp/grx500-trial-accept;;
esac
if [ "$CTL_ACTION" = accept ]; then
 ( set -- accept; . /work/trialctl.sh ) || exit 13
elif [ "$CTL_ACTION" = reject ]; then
 ( set -- reject; . /work/trialctl.sh ) || exit 13
 exit 14
elif [ "$CTL_ACTION" = accept_then_reject ]; then
 ( set -- accept; . /work/trialctl.sh ) || exit 13
 ( set -- reject; . /work/trialctl.sh ) || exit 13
 grx500_trial_commit && exit 15
 exit 14
elif [ "$CTL_ACTION" = commit_then_reject ]; then
 ( set -- accept; . /work/trialctl.sh ) || exit 13
 grx500_trial_commit || exit 12
 ( set -- reject; . /work/trialctl.sh ) && exit 15
 exit 0
elif [ "$CTL_ACTION" = race_reject ]; then
 ( set -- accept; . /work/trialctl.sh ) || exit 13
 grx500_trial_commit & commit_pid=$!
 while [ ! -e /work/commit-entered ]; do sleep .01; done
 ( touch /work/reject-started; set -- reject; . /work/trialctl.sh ) & reject_pid=$!
 while [ ! -e /work/reject-started ]; do sleep .01; done
 touch /work/release-commit
 wait "$commit_pid" || exit 12
 wait "$reject_pid" && exit 15
 exit 0
elif [ "$CTL_ACTION" = failed_commit_then_reject ]; then
 ( set -- accept; . /work/trialctl.sh ) || exit 13
 grx500_trial_commit && exit 15
 grx500_trial_commit && exit 15
 ( set -- reject; . /work/trialctl.sh ) && exit 15
 ( set -- status; . /work/trialctl.sh ) > /work/trial-status || exit 13
 [ "$(cat /work/trial-status)" = 'boot environment save attempted; boot decision needs inspection' ] || exit 13
 exit 16
fi
[ "$MARK_FAILED_BEFORE_COMMIT" != 1 ] || touch /tmp/grx500-trial-failed
grx500_trial_commit || exit 12
[ "$LOCK_SENTINEL" != 1 ] || [ "$(cat /tmp/grx500-trial-lock/decision.lock)" = retain ] || exit 18
'''
class Trial(unittest.TestCase):
 def test_preinit_mktemp_failure_schedules_fallback(self):
  source=(BASE/'lib/preinit/79_grx500_trial').read_text()
  # The failure precedes every sourced helper call. Replace only those three
  # leaf imports so the real preinit control flow runs in the private root.
  source,n=re.subn(r'^\t\. /lib/(?:upgrade/nand\.sh|functions/grx500-factory\.sh|functions/grx500-trial\.sh)$',
                   '\t:',source,flags=re.M)
  self.assertEqual(n,3)
  service=(BASE/'etc/init.d/grx500-trial').read_text()
  harness='''#!/bin/sh
board_name() { echo "$TEST_BOARD"; }
boot_hook_add() { :; }
mkdir() { :; }
mktemp() { return 1; }
procd_open_instance() { touch /tmp/worker-started; }
procd_set_param() { :; }
procd_close_instance() { :; }
'''+source+service+'''
grx500_trial_preinit
start_service
if [ "$EXPECT_FALLBACK" = 1 ]; then
  [ -f /tmp/grx500-trial-failed ] && [ -f /tmp/worker-started ]
else
  [ ! -e /tmp/grx500-trial-failed ] && [ ! -e /tmp/worker-started ]
fi
'''
  for marker,initramfs,board,expected in [
   (True,'0','tplink,archer-ax3000-v1','1'),
   (False,'0','tplink,archer-ax3000-v1','0'),
   (True,'1','tplink,archer-ax3000-v1','0'),
   (True,'0','other-board','0')]:
   with self.subTest(marker=marker,initramfs=initramfs,board=board):
    with tempfile.TemporaryDirectory(prefix='grx500-preinit-test-') as tmp:
     w=Path(tmp);(w/'etc').mkdir();(w/'harness').write_text(harness)
     if marker:(w/'etc/grx500-factory-install').touch()
     cmd=['bwrap','--unshare-all','--die-with-parent','--new-session',
          '--cap-drop','ALL','--clearenv','--tmpfs','/',
          '--ro-bind','/usr','/usr','--symlink','usr/bin','/bin',
          '--symlink','usr/lib','/lib','--symlink','usr/lib','/lib64',
          '--dev','/dev','--tmpfs','/tmp','--bind',str(w/'etc'),'/etc',
          '--bind',str(w),'/work','--setenv','PATH','/usr/bin',
          '--setenv','INITRAMFS',initramfs,'--setenv','TEST_BOARD',board,
          '--setenv','EXPECT_FALLBACK',expected]
     if os.environ.get('GRX500_TEST_QEMU'):
      target=Path(os.environ['GRX500_TEST_ROOT'])
      cmd+=['--ro-bind',os.environ['GRX500_TEST_QEMU'],'/qemu',
            '--ro-bind',str(target/'lib'),'/target/lib',
            '--ro-bind',str(target/'bin/busybox'),'/target/busybox']
      shell=['/qemu','-L','/target','/target/busybox','sh','/work/harness']
     else:shell=['/usr/bin/bash','/work/harness']
     result=subprocess.run(cmd+shell,text=True,capture_output=True,timeout=20)
     self.assertEqual(result.returncode,0,result.stderr)
 def run_case(self,bank='B',state='0',**options):
  with tempfile.TemporaryDirectory(prefix='grx500-trial-test-') as tmp:
   w=Path(tmp)
   def write(name,data):
    p=w/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
   contract=(BASE/'etc/grx500-boot-contract').read_text()
   env=dict(line.split('=',1) for line in contract.splitlines());env.update(update_chk=state,active_bank=bank)
   if options.pop('BAD_CONTRACT',False):env['check_image1']='reset'
   if options.pop('BAD_ACTIVE',False):env['active_bank']='A' if bank=='B' else 'B'
   if options.pop('TRAILING_SPACE',False):env['addmisc']+=' '
   volumes={n:'ubi0_'+str(i) for i,n in enumerate(['kernelA','rootfsA','kernelB','rootfsB','bootcoreA','bootcoreB','data_vol'])}
   if options.pop('NO_STOCK_DATA',False):del volumes['data_vol']
   if options.pop('EXISTING_OVERLAY',False):volumes['rootfs_data']='ubi0_9'
   if options.pop('EXISTING_STAGE',False):volumes['openwrt-trial-data']='ubi0_9'
   if options.pop('MISSING_CORE',False):del volumes['bootcoreA']
   original=dict(env)
   write('state.json',json.dumps(dict(env=env,volumes=volumes,calls=[])))
   write('etc/grx500-boot-contract',contract);write('trial.sh',(BASE/'lib/functions/grx500-trial.sh').read_text())
   helper,n=re.subn(r'^\. /lib/(?:functions\.sh|upgrade/nand\.sh|functions/grx500-factory\.sh|functions/grx500-trial\.sh)$',
                    ':',TRIALCTL.read_text(),flags=re.M)
   self.assertEqual(n,4)
   write('trialctl.sh',helper)
   write('etc/grx500-factory-install','')
   write('harness',HARNESS);write('env.config','fixture\n')
   write('proc/cmdline',options.pop('CMDLINE','rootfsname=rootfs'+bank)+'\n')
   write('proc/sys/kernel/random/boot_id','11111111-2222-3333-4444-555555555555\n')
   vid=1 if bank=='A' else 3
   write('proc/self/mountinfo',f'1 0 254:{vid} / / ro - squashfs /dev/root ro\n')
   write('mountinfo-after',f'1 0 254:{vid} / /rom ro - squashfs /dev/root ro\n')
   write('proc/mounts','/dev/ubi0_10 /overlay ubifs rw 0 0\n')
   for i in [1,2]:
    write(f'sys/class/mtd/mtd{i}/flags','0x0' if options.get('READONLY') else '0x400')
    for k,v in dict(offset=str(1048576 if i==1 else 1310720),size='262144',erasesize='131072',writesize='2048',type='nand').items():
     write(f'sys/class/mtd/mtd{i}/'+k,v)
   field=options.pop('MTD_FIELD',None)
   if field:write('sys/class/mtd/mtd1/'+field,options.pop('MTD_VALUE'))
   free_ebs=options.pop('FREE_EBS','100')
   for k,v in dict(mtd_num='5',eraseblock_size='126976',avail_eraseblocks='0' if options.pop('NO_SPACE',False) else free_ebs).items():write('sys/class/ubi/ubi0/'+k,v)
   write(f'sys/class/block/ubiblock0_{vid}/dev',f'254:{vid}')
   write('sys/class/net/br-lan/address','10:aa:bb:cc:dd:fe');write('sys/class/net/br-lan/carrier','1')
   write('sys/class/net/wan/health-placeholder','ok')
   for port in ['lan1','lan2','lan3','lan4']:
    (w/f'sys/class/net/{port}/brport').mkdir(parents=True)
    (w/f'sys/class/net/{port}/brport/bridge').symlink_to('/sys/class/net/br-lan')
   for p in [0,1]:(w/f'sys/class/ieee80211/phy{p}').mkdir(parents=True)
   for p in [0,2]:write(f'firmware/cal_wlan{p}.bin','fixture')
   for p in ['bin','overlay']:(w/p).mkdir()
   write('bin/mock',MOCK);(w/'bin/mock').chmod(0o755)
   for cmd in ['fw_printenv','fw_setenv','find-volume','ubimkvol','ubirename','mount','umount','ubus','jsonfilter','iw','pidof']:(w/'bin'/cmd).symlink_to('mock')
   cmd=['bwrap','--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv','--tmpfs','/','--ro-bind','/usr','/usr','--symlink','usr/bin','/bin','--symlink','usr/lib','/lib','--symlink','usr/lib','/lib64','--dev','/dev','--tmpfs','/tmp','--symlink','tmp','/var','--bind',str(w),'/work']
   for part in ['etc','sys','proc','overlay']:cmd+=['--bind',str(w/part),'/'+part]
   for i in [1,2]:cmd+=['--ro-bind','/dev/null',f'/dev/mtd{i}']
   # /lib is read-only; supply factory calibration through a dedicated submount.
   cmd+=['--ro-bind',str(w/'firmware'),'/usr/lib/firmware','--setenv','PATH','/work/bin:/usr/bin']
   for k,v in options.items():cmd+=['--setenv',k,str(v)]
   if os.environ.get('GRX500_TEST_QEMU'):
    target=Path(os.environ['GRX500_TEST_ROOT'])
    write('bin/flock','#!/bin/sh\nexec /qemu -L /target /target/busybox flock "$@"\n')
    (w/'bin/flock').chmod(0o755)
    cmd+=['--ro-bind',os.environ['GRX500_TEST_QEMU'],'/qemu','--ro-bind',str(target/'lib'),'/target/lib','--ro-bind',str(target/'bin/busybox'),'/target/busybox']
    shell=['/qemu','-L','/target','/target/busybox','sh','/work/harness']
   else:shell=['/usr/bin/bash','/work/harness']
   result=subprocess.run(cmd+shell,text=True,capture_output=True,timeout=20)
   s=json.loads((w/'state.json').read_text())
   s['rebooted']=(w/'rebooted').exists()
   s['failed']=(w/'failed').exists()
   return result,original,s
 def test_both_trials_commit_once(self):
  for bank,state,new in [('B','0','2'),('A','2','0')]:
   with self.subTest(bank=bank):
    p,old,s=self.run_case(bank,state);self.assertEqual(p.returncode,0,p.stderr)
    self.assertEqual(s['env'],dict(old,update_chk=new));self.assertEqual(sum(c[0]=='fw_setenv' for c in s['calls']),1)
    self.assertEqual(s['volumes']['rootfs_data'],'ubi0_10')
 def test_startup_prerequisites_cannot_accept_networking(self):
  # Every old readiness condition passes, with no Ethernet packet exchange,
  # running AP or wireless association. Neither bank may become permanent.
  for bank,state in [('B','0'),('A','2')]:
   with self.subTest(bank=bank):
    p,old,s=self.run_case(bank,state,MOCK_ACCEPTANCE='0')
    self.assertEqual(p.returncode,12,p.stderr)
    self.assertEqual(s['env'],old)
    self.assertFalse(any(c[0]=='fw_setenv' for c in s['calls']))
 def test_acceptance_is_bound_to_bank_and_boot(self):
  for marker in ('none','wrong_bank','stale_boot'):
   with self.subTest(marker=marker):
    p,old,s=self.run_case('B','0',MOCK_ACCEPTANCE='0',ACCEPT_MARKER=marker)
    self.assertEqual(p.returncode,12,p.stderr)
    self.assertEqual(s['env'],old)
    self.assertFalse(any(c[0]=='fw_setenv' for c in s['calls']))
  for bank,state in [('B','0'),('A','2')]:
   with self.subTest(bank=bank):
    p,old,s=self.run_case(bank,state,MOCK_ACCEPTANCE='0',ACCEPT_MARKER='valid')
    self.assertEqual(p.returncode,0,p.stderr)
    self.assertEqual(s['env']['update_chk'],'2' if bank=='B' else '0')
    self.assertEqual(sum(c[0]=='fw_setenv' for c in s['calls']),1)
 def test_explicit_trial_control_requires_root_and_health(self):
  for opts in (dict(TEST_UID='1000'),dict(FAIL_HEALTH='1')):
   with self.subTest(opts=opts):
    p,old,s=self.run_case(MOCK_ACCEPTANCE='0',CTL_ACTION='accept',**opts)
    self.assertEqual(p.returncode,13,p.stderr)
    self.assertEqual(s['env'],old)
    self.assertFalse(any(c[0]=='fw_setenv' for c in s['calls']))
  for bank,state in [('B','0'),('A','2')]:
   with self.subTest(bank=bank):
    p,old,s=self.run_case(bank,state,MOCK_ACCEPTANCE='0',CTL_ACTION='accept')
    self.assertEqual(p.returncode,0,p.stderr)
    self.assertEqual(s['env']['update_chk'],'2' if bank=='B' else '0')
    self.assertEqual(sum(c[0]=='fw_setenv' for c in s['calls']),1)
 def test_explicit_rejection_requests_fallback_without_commit(self):
  for bank,state in [('B','0'),('A','2')]:
   with self.subTest(bank=bank):
    p,old,s=self.run_case(bank,state,MOCK_ACCEPTANCE='0',CTL_ACTION='reject')
    self.assertEqual(p.returncode,14,p.stderr)
    self.assertEqual(s['env'],old)
    self.assertTrue(s['rebooted'])
    self.assertTrue(s['failed'])
    self.assertFalse(any(c[0]=='fw_setenv' for c in s['calls']))
 def test_acceptance_rejection_decision_order(self):
  for action,expected,new_state in [('accept_then_reject',14,'0'),
                                    ('commit_then_reject',0,'2'),
                                    ('race_reject',0,'2')]:
   with self.subTest(action=action):
    p,old,s=self.run_case(MOCK_ACCEPTANCE='0',CTL_ACTION=action,
                          PAUSE_COMMIT='1' if action=='race_reject' else '0')
    self.assertEqual(p.returncode,expected,p.stderr)
    self.assertEqual(s['env']['update_chk'],new_state)
    self.assertEqual(sum(c[0]=='fw_setenv' for c in s['calls']),0 if expected==14 else 1)
    self.assertEqual(s['failed'],expected==14)
  p,old,s=self.run_case(MOCK_ACCEPTANCE='0',ACCEPT_MARKER='valid',MARK_FAILED_BEFORE_COMMIT='1')
  self.assertEqual(p.returncode,12,p.stderr)
  self.assertEqual(s['env'],old)
  self.assertFalse(any(c[0]=='fw_setenv' for c in s['calls']))
  p,old,s=self.run_case(MOCK_ACCEPTANCE='0',ACCEPT_MARKER='valid',NO_DECISION_LOCK='1')
  self.assertEqual(p.returncode,12,p.stderr)
  self.assertEqual(s['env'],old)
  self.assertFalse(any(c[0]=='fw_setenv' for c in s['calls']))
  p,old,s=self.run_case(LOCK_SENTINEL='1')
  self.assertEqual(p.returncode,0,p.stderr)
  self.assertEqual(sum(c[0]=='fw_setenv' for c in s['calls']),1)
  p,old,s=self.run_case(MOCK_ACCEPTANCE='0',CTL_ACTION='failed_commit_then_reject',FAIL_CMD='fw_setenv')
  self.assertEqual(p.returncode,16,p.stderr)
  self.assertEqual(s['env'],old)
  self.assertFalse(s['rebooted'])
  self.assertEqual(sum(c[0]=='fw_setenv' for c in s['calls']),1)
 def test_stock_data_volume_fallback_capacity(self):
  # The stock preinit creates a 20 MiB data_vol when it is absent. The trial
  # must reserve that capacity in addition to its own 8 MiB overlay.
  p,old,s=self.run_case(FREE_EBS='66')
  self.assertEqual(p.returncode,11,p.stderr)
  self.assertEqual(s['env'],old)
  self.assertFalse(any(c[0]=='ubimkvol' for c in s['calls']))
  p,old,s=self.run_case(FREE_EBS='67')
  self.assertEqual(p.returncode,0,p.stderr)
  self.assertEqual(s['volumes']['rootfs_data'],'ubi0_10')
  for free in ('232','0'):
   with self.subTest(free=free):
    p,old,s=self.run_case(NO_STOCK_DATA=1,FREE_EBS=free)
    self.assertEqual(p.returncode,11,p.stderr)
    self.assertEqual(s['env'],old)
    self.assertFalse(any(c[0]=='ubimkvol' for c in s['calls']))
  p,old,s=self.run_case(NO_STOCK_DATA=1,FREE_EBS='233')
  self.assertEqual(p.returncode,0,p.stderr)
  self.assertNotIn('data_vol',s['volumes'])
  self.assertEqual(s['volumes']['rootfs_data'],'ubi0_10')
 def test_stable_boot_does_nothing(self):
  for bank,state in [('A','0'),('B','2')]:
   p,old,s=self.run_case(bank,state);self.assertEqual(p.returncode,0,p.stderr)
   self.assertEqual(s['env'],old);self.assertTrue(all(c[0]=='fw_printenv' for c in s['calls']))
 def test_actual_stock_addmisc_terminator(self):
  p,old,s=self.run_case(TRAILING_SPACE=True);self.assertEqual(p.returncode,0,p.stderr)
  self.assertEqual(s['env'],dict(old,update_chk='2'))
 def test_preflight_never_mutates(self):
  for opts in [dict(BAD_CONTRACT=1),dict(BAD_ACTIVE=1),dict(NO_SPACE=1),dict(EXISTING_OVERLAY=1),dict(EXISTING_STAGE=1),dict(MISSING_CORE=1),dict(READONLY=1),dict(CMDLINE=''),dict(CMDLINE='rootfsname=rootfsB rootfsname=rootfsA'),dict(BOARD='wrong')]:
   with self.subTest(opts=opts):
    p,old,s=self.run_case(**opts);self.assertEqual(p.returncode,11,p.stderr)
    self.assertEqual(s['env'],old);self.assertTrue(all(c[0] in ['fw_printenv','find-volume'] for c in s['calls']))
 def test_failures_never_commit(self):
  for opts in [dict(FAIL_CMD='ubimkvol'),dict(FAIL_CMD='mount'),dict(FAIL_CMD='umount'),dict(FAIL_CMD='ubirename'),dict(FAIL_HEALTH='1')]:
   with self.subTest(opts=opts):
    p,old,s=self.run_case(**opts);self.assertNotEqual(p.returncode,0,p.stderr)
    self.assertEqual(s['env'],old);self.assertFalse(any(c[0]=='fw_setenv' for c in s['calls']))
 def test_commit_failure_is_not_retried(self):
  for opts in [dict(FAIL_CMD='fw_setenv'),dict(BAD_READBACK='1')]:
   p,old,s=self.run_case(**opts);self.assertEqual(p.returncode,12,p.stderr)
   self.assertEqual(sum(c[0]=='fw_setenv' for c in s['calls']),1)
 def test_exact_environment_geometry(self):
  p,old,s=self.run_case(MODE='config');self.assertEqual(p.returncode,0,p.stderr)
  self.assertEqual(p.stdout,'/dev/mtd1 0 0x4000 0x20000 2\n/dev/mtd2 0 0x4000 0x20000 2\n')
  self.assertEqual(s['calls'],[])
  for field,value in [('offset','0'),('size','16384'),('erasesize','4096'),('writesize','4096'),('type','nor')]:
   with self.subTest(field=field):
    p,old,s=self.run_case(MODE='config',MTD_FIELD=field,MTD_VALUE=value)
    self.assertNotEqual(p.returncode,0);self.assertEqual(s['calls'],[])
if __name__=='__main__':unittest.main()
