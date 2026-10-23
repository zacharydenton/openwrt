#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the exact stock kernel-bank shell function with mocked write leaves.

Only the selected function body executes, under bash. NAND/UBI writes and
environment operations are logged fixtures. This models control flow, not
flash persistence, environment CRCs, power loss or U-Boot execution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE_SHA = '7ea7ec9dd7326b346d22909d1051de517d13d38f5778144c48168021265e8208'
HARNESS = r'''
sed() {
 local a; local -a args=()
 for a in "$@"; do
  if [ "$a" = /proc/cmdline ]; then args+=("$FIXTURE_CMDLINE"); else args+=("$a"); fi
 done
 command sed "${args[@]}"
}
write_vol_stdin() {
 printf 'write\t%s\t%s\n' "$1" "$2" >> "$FIXTURE_LOG"
 return "$FIXTURE_WRITE_STATUS"
}
uboot_env() {
 printf 'env\t%s\t%s\n' "$3" "$5" >> "$FIXTURE_LOG"
 [ "$3" != "$FIXTURE_FAIL_ENV" ]
}
upgrade_dualvol_kernel 13118188
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vol-mgmt', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw = a.vol_mgmt.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        p.error('unexpected stock vol_mgmt')
    match = re.search(r'^upgrade_dualvol_kernel \(\)\n\{\n.*?^\}\n', raw.decode(), re.M | re.S)
    assert match
    cases = []
    with tempfile.TemporaryDirectory(prefix='stock-bank-') as tmp:
        work = Path(tmp)
        script = work / 'test.sh'; script.write_text(match.group() + HARNESS)
        for bank in ('A', 'B'):
            other = 'B' if bank == 'A' else 'A'
            expected_env = [['env', 'f_kernel_size' + other, format(13118188, 'X')],
                            ['env', 'active_bank', other],
                            ['env', 'update_chk', '1' if other == 'B' else '3']]
            for failure in ('none', 'write', 'f_kernel_size' + other, 'active_bank', 'update_chk'):
                cmdline = work / 'cmdline'; cmdline.write_text('console=ttyLTQ0 active_bank=' + bank + ' update_chk=0\n')
                log = work / 'calls'; log.write_text('')
                env = dict(PATH='/usr/bin:/bin', FIXTURE_CMDLINE=str(cmdline), FIXTURE_LOG=str(log),
                           FIXTURE_WRITE_STATUS='1' if failure == 'write' else '0',
                           FIXTURE_FAIL_ENV=failure if failure not in ('none', 'write') else '')
                r = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True, timeout=10)
                calls = [line.split('\t') for line in log.read_text().splitlines()]
                expected = [['write', 'kernel' + other, '13118188']]
                if failure != 'write':
                    expected += expected_env
                passed = calls == expected
                cases.append(dict(bank=bank, fault=failure, passed=passed, exit_code=r.returncode,
                                  calls=calls, environment_changed_after_injected_env_failure=
                                  failure.startswith('f_kernel_size') or failure == 'active_bank'))
                print(('PASS' if passed else 'FAIL') + ': bank ' + bank + ', fault ' + failure)
    report = dict(passed=all(c['passed'] for c in cases), cases=cases, stock_script_sha256=SOURCE_SHA,
                  function_sha256=hashlib.sha256(match.group().encode()).hexdigest(),
                  hardware_tested=False, flash_operations_performed=False,
                  observations=['A failed kernel write prevents the environment-update sequence.',
                    'The three environment writes are separate; earlier failures do not stop later updates.',
                    'The stock updater therefore cannot provide an atomic bank-switch guarantee.'],
                  limitations=['Only the exact selected shell function executes; leaf operations are fixtures.',
                               'Host bash, not the router kernel or flash hardware, executes this model.'])
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
