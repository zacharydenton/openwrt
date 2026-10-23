#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the real trial worker with isolated acceptance, clock and reboot leaves."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


WORKER = Path(__file__).resolve().parents[1] / "base-files/usr/libexec/grx500-trial"
MOCKS = r'''#!/bin/sh
printf '0\n' > /work/polls
[ "$MARK_FAILED" = 1 ] && touch /tmp/grx500-trial-failed
[ "$MARK_COMMIT_STARTED" = 1 ] && touch /tmp/grx500-trial-commit-started
[ "$PRECREATE_LOCK" = 1 ] && mkdir -m 0700 /tmp/grx500-trial-lock
[ "$BAD_LOCK_MODE" = 1 ] && mkdir -m 0777 /tmp/grx500-trial-lock
[ "$BAD_LOCK_SYMLINK" = 1 ] && ln -s /work /tmp/grx500-trial-lock
if [ "$HOLD_WORKER_LOCK" = 1 ]; then
    mkdir -m 0700 /tmp/grx500-trial-lock
    exec 7<>/tmp/grx500-trial-lock/worker.lock
    flock -x 7
fi
grx500_trial_config() { [ "$CONFIG_FAIL" != 1 ] && printf 'fixture\n'; }
grx500_trial_context() { return 0; }
grx500_trial_volume_context() { return 0; }
grx500_trial_health() { return 0; }
grx500_trial_acceptance() {
    [ "$ACCEPT_AFTER" != never ] && [ "$(cat /work/polls)" -ge "$ACCEPT_AFTER" ]
}
grx500_trial_commit() {
    printf 'commit\n' >> /work/events
    [ "$COMMIT_ATTEMPTED" = 1 ] && touch /tmp/grx500-trial-commit-started
    [ "$COMMIT_FAIL" != 1 ]
}
sleep() { printf '%s\n' "$(($(cat /work/polls) + 1))" > /work/polls; }
logger() { :; }
sync() { :; }
reboot() { printf 'reboot\n' >> /work/events; }
'''


class Worker(unittest.TestCase):
    def run_case(self, **options):
        source, count = re.subn(
            r'^\. /lib/(?:functions\.sh|upgrade/nand\.sh|functions/grx500-factory\.sh|functions/grx500-trial\.sh)$',
            ':', WORKER.read_text(), flags=re.M,
        )
        self.assertEqual(count, 4)
        with tempfile.TemporaryDirectory(prefix='grx500-worker-') as tmp:
            work = Path(tmp)
            (work / 'harness').write_text(MOCKS + source)
            command = [
                'bwrap', '--unshare-all', '--die-with-parent', '--new-session',
                '--cap-drop', 'ALL', '--clearenv', '--tmpfs', '/',
                '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
                '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64',
                '--dev', '/dev', '--tmpfs', '/tmp', '--bind', str(work), '/work',
                '--setenv', 'PATH', '/usr/bin',
            ]
            for key, value in options.items():
                command += ['--setenv', key, str(value)]
            if os.environ.get('GRX500_TEST_QEMU'):
                target = Path(os.environ['GRX500_TEST_ROOT'])
                command += [
                    '--ro-bind', os.environ['GRX500_TEST_QEMU'], '/qemu',
                    '--ro-bind', str(target / 'lib'), '/target/lib',
                    '--ro-bind', str(target / 'bin/busybox'), '/target/busybox',
                ]
                shell = ['/qemu', '-L', '/target', '/target/busybox', 'sh', '/work/harness']
            else:
                shell = ['/usr/bin/bash', '/work/harness']
            result = subprocess.run(command + shell, text=True, capture_output=True, timeout=30)
            events = (work / 'events').read_text().splitlines() if (work / 'events').exists() else []
            polls = int((work / 'polls').read_text())
            return result, events, polls

    def test_accepts_once_after_manual_signal(self):
        result, events, polls = self.run_case(ACCEPT_AFTER=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['commit'])
        self.assertEqual(polls, 3)

    def test_timeout_returns_to_stock(self):
        result, events, polls = self.run_case(ACCEPT_AFTER='never')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(events, ['reboot'])
        self.assertEqual(polls, 360)

    def test_failed_commit_is_not_retried(self):
        result, events, polls = self.run_case(ACCEPT_AFTER=0, COMMIT_FAIL=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(events, ['commit', 'reboot'])
        self.assertEqual(polls, 0)

    def test_uncertain_environment_save_keeps_trial_running(self):
        result, events, polls = self.run_case(
            ACCEPT_AFTER=0, COMMIT_FAIL=1, COMMIT_ATTEMPTED=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(events, ['commit'])
        self.assertEqual(polls, 0)
        for config_fail in (0, 1):
            result, events, polls = self.run_case(
                ACCEPT_AFTER=0, MARK_COMMIT_STARTED=1, CONFIG_FAIL=config_fail)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(events, [])
            self.assertEqual(polls, 0)

    def test_preparation_failures_reboot_without_commit(self):
        for options in (dict(ACCEPT_AFTER=0, MARK_FAILED=1),
                        dict(ACCEPT_AFTER=0, CONFIG_FAIL=1)):
            with self.subTest(options=options):
                result, events, polls = self.run_case(**options)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(events, ['reboot'])
                self.assertEqual(polls, 0)

    def test_restart_reuses_private_lock_directory(self):
        result, events, polls = self.run_case(ACCEPT_AFTER=0, PRECREATE_LOCK=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['commit'])
        self.assertEqual(polls, 0)

    def test_insecure_lock_directory_fails_closed(self):
        for option in ('BAD_LOCK_MODE', 'BAD_LOCK_SYMLINK'):
            with self.subTest(option=option):
                result, events, polls = self.run_case(ACCEPT_AFTER=0, **{option: 1})
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(events, [])
                self.assertEqual(polls, 0)

    def test_second_worker_cannot_run_concurrently(self):
        result, events, polls = self.run_case(ACCEPT_AFTER=0, HOLD_WORKER_LOCK=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(events, [])
        self.assertEqual(polls, 0)


if __name__ == '__main__':
    unittest.main()
