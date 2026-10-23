#!/usr/bin/env python3
"""Exercise shipped reload control flow with temporary paths and mocked commands.
Never invokes real ubus, module tools, wireless interfaces or target binaries.
"""
from pathlib import Path
import os
import subprocess
import tempfile

source = (Path(__file__).resolve().parent.parent / 'recovery/iwlwav-recover').read_text()
with tempfile.TemporaryDirectory(prefix='iwlwav-recovery-test-') as tmp:
    root = Path(tmp)
    bindir = root / 'bin'
    bindir.mkdir()
    firmware = root / 'firmware'
    firmware.mkdir()
    for name in ('cal_wlan0.bin', 'cal_wlan2.bin'):
        (firmware / name).write_bytes(b'per-device-test-fixture')
    (root / 'module').mkdir()
    script = root / 'recover'
    script.write_text(source.replace('/var/run/iwlwav-recovery', str(root / 'state'))
                     .replace('/lib/firmware/', str(firmware) + '/')
                     .replace('/sys/module/mtlk', str(root / 'module')))
    mocks = {
        'logger': 'printf "log %s\\n" "$*" >> "$MOCK_LOG"',
        'ubus': 'printf "ubus %s\\n" "$*" >> "$MOCK_LOG"; [ "$MOCK_DOWN_FAIL" != 1 ] || [ "$5" != down ]',
        'rmmod': 'echo rmmod >> "$MOCK_LOG"; [ "$MOCK_BUSY" != 1 ]',
        'kmodloader': 'echo "load $*" >> "$MOCK_LOG"; [ "$MOCK_LOAD_FAIL" != 1 ]',
        'timeout': 'shift 3; "$@"',
        'sleep': 'exit 0',
    }
    for name, body in mocks.items():
        p = bindir / name
        p.write_text('#!/bin/sh\n' + body + '\n')
        p.chmod(0o755)
    env = dict(os.environ, PATH=str(bindir) + ':/usr/bin:/bin', MOCK_LOG=str(root / 'calls'))
    def run(**flags):
        (root / 'calls').write_text('')
        proc = subprocess.run(['/bin/sh', str(script)], env=dict(env, **flags), capture_output=True, text=True)
        return proc.returncode, (root / 'calls').read_text()
    def reset():
        (root / 'state').unlink(missing_ok=True)
    rc, calls = run()
    assert rc == 0 and calls.index('rmmod') < calls.index('load ') < calls.index('wireless up'), calls
    assert not (root / 'state.lock').exists()
    rc, calls = run()
    assert rc == 0
    rc, calls = run()
    assert rc == 0
    rc, calls = run()
    assert rc != 0 and 'rmmod' not in calls and 'limit reached' in calls
    reset()
    rc, calls = run(MOCK_BUSY='1')
    assert rc != 0 and calls.count('rmmod') == 3 and 'load /' not in calls and 'wireless up' in calls
    reset()
    rc, calls = run(MOCK_LOAD_FAIL='1')
    assert rc != 0 and 'reload failed' in calls and 'wireless up' in calls
    reset()
    rc, calls = run(MOCK_DOWN_FAIL='1')
    assert rc != 0 and 'rmmod' not in calls
    reset()
    (firmware / 'cal_wlan2.bin').unlink()
    rc, calls = run()
    assert rc != 0 and 'ubus' not in calls and 'calibration missing' in calls
    (root / 'state.lock').mkdir()
    rc, calls = run()
    assert rc == 0 and not calls
print('PASS: complete-recovery helper ordering, 3/10min limit, lock exclusion, calibration gate, bounded busy retry and unload/load/netifd failures')
