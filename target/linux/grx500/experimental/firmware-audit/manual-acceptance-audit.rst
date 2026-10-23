Manual first-boot acceptance model
==================================

The earlier factory candidate could commit the new bank when its bridge had
carrier and two wiphys existed, without Ethernet packet exchange or an active
Wi-Fi AP. That candidate remains withdrawn. The current opt-in factory source
never infers acceptance from those startup checks.

The factory-only ``grx500-trialctl`` command offers ``status``, ``accept`` and
``reject``. ``accept`` requires root, the opt-in marker, a pending trial, the
expected saved stock boot contract and a healthy mounted trial. It writes a
tmpfs marker containing the running bank and kernel boot ID. The worker checks
that marker and repeats the boot, volume and health checks before its single
redundant-environment transaction. A marker from another bank or boot cannot
commit. ``reject`` requests reboot without changing the saved bank. Without
acceptance, the worker requests reboot after 30 minutes. The old stable bank
remains selected in the saved environment until commitment.

Acceptance, rejection and the worker's environment save use one advisory
``flock`` lock in a private, root-owned tmpfs directory. The worker creates
the directory once per boot and leaves it in place on exit, so a late command
cannot replace the lock file while another decision is in progress. A restarted
worker reuses it only when it is still owned by its effective user with mode
0700, and a separate nonblocking lock prevents concurrent worker loops. The worker
checks the rejection marker while holding it and keeps the lock through
environment readback and removal of the pending marker.
If rejection wins first, the worker cannot commit. If commitment wins first,
``reject`` sees no pending trial and refuses to promise a stock fallback.
The worker marks the start of its environment save under the same lock. If the
save or readback fails, the marker remains and ``reject`` refuses to claim the
saved decision is still reversible; ``status`` reports the uncertainty. The
worker does not automatically reboot after that marker exists, leaving the
running trial available for inspection. A worker restart also respects it.

The command is intended to be run over the trial's LAN management connection
after a person tests Ethernet, both radios and the rest of the device. It does
not itself prove Wi-Fi association, packet throughput, USB function, settings
persistence, reset or stock fallback. Wi-Fi is disabled by default and must be
configured for testing. A reboot before acceptance is expected to return to
stock under the researched bootloader defaults, but that behavior has not been
observed on this router. There is no hardware watchdog to recover a hard
lockup, and no factory image is approved for upload.

``tests/test-trial.py`` executes the actual shell predicate and factory control
body in isolated native and packaged-MIPS shells. Its cases reject absent,
wrong-bank and stale-boot markers; non-root or unhealthy control requests do
not write the boot environment, and explicit rejection requests reboot without
commitment. They also exercise both decision orderings and hold the environment
write while a concurrent rejection waits for the lock. A missing private
directory fails closed before an environment save. ``tests/test-trial-worker.py`` runs the actual
worker with mocked clock, reboot and flash leaves; it covers delayed manual
acceptance, timeout, preparation failure, failed commit without retry,
safe reuse of the private lock directory, exclusion of a second worker and
no automatic reboot after an uncertain environment save.
``manual-acceptance-results.json`` binds those results to the rebuilt factory
image and packaged command. These tests do not execute physical NAND, network
traffic or a router reset.
