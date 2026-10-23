Removal must complete its scan barrier even under allocation failure
===================================================================

Patch 256 closed asynchronous channel-request admission, but its completion
guarantee still depended on a fallible ordinary user request. The removal
caller ignored the return from ``_wave_radio_abort_and_prevent_scan``. A
clipboard allocation, clipboard-copy allocation or core command-context
allocation could fail before enqueue. DUT/IGNORE recovery readiness could
also reject the request before enqueue. A disabled ALTER_SCAN ability could
let the FIFO barrier complete without aborting the active scan.

The historical failure fixture extracts the actual invocation, abort helper
and radio-quiesce functions. With modeled allocation/dispatch leaves it
reproduces all five failures, including four returns with an earlier channel
request still queued and all five with a scan still active. The ordinary
control completes both. The report is ``scan-barrier-failure-results.json``;
its failed release gate describes the pre-257 implementation. Reproduction
against the current prepared tree reverses patch 257 only in a temporary copy::

  python3 target/linux/grx500/experimental/firmware-audit/verify-scan-barrier-failure.py \
    build_dir/target-mips_24kc_musl/linux-grx500_generic/iwlwav-stock-6.0.8.0.87.0.7 \
    --before-patch package/kernel/iwlwav-stock/patches/257-removal-scan-barrier.patch \
    --expect-vulnerable --output /tmp/scan-barrier-before.json

Without ``--expect-vulnerable``, the unsafe historical behavior returns status
1. Reproducing a defect is not a successful release check.

Correction and lifecycle contract
---------------------------------

Patch 257 makes radio removal call ``mtlk_core_scan_quiesce`` after closing
the channel gate and cancelling control timers. This function initializes a
stack-owned serializer command and Linux completion. Enqueue does not allocate
a clipboard, request payload or core execution wrapper. Its user priority is
the same FIFO used by SET_CHAN and CAC_TIMEOUT, so it follows all admitted
channel requests rather than overtaking them. A completion wait retains both
the command and its context until the callback has finished.

The callback directly calls ``abort_scan_sync`` and ``pause_or_prevent_scan``.
It is local removal work, so it does not pass through the user-command
readiness/ability checks or the recovery cancellation-flag wrapper. Existing
``removal_pending`` handling suppresses channel restoration to firmware during
scan cleanup. Ordinary scan commands continue to use the existing interface.

If command initialization or enqueue fails, or a command is explicitly
cancelled without execution, removal calls serializer stop first. Stop closes
admission, drains queued work and joins the worker. Only then may the removal
thread perform local scan cleanup itself. The serializer has a new
``stop_done`` lifecycle guard so subsequent normal VAP cleanup can call stop
again without violating the vendor startup macros or releasing resources twice.
Initialization marks it stopped; each start clears the guard before attempting
startup, preserving partial-start rollback.

This API belongs to the card-removal owner. The initialized master remains
alive until later VAP teardown, and dynamic VAP deletion rejects the master.
Recovery does not start or stop its serializer. Concurrent lifecycle owners
are not supported by ``stop_done``; it is not a synchronization lock. The
exceptional fallback must finish the worker join before the core or netdev is
freed. A permanently hung worker still blocks removal; returning while it owns
callbacks would be unsafe.

Verification and limits
-----------------------

``tests/removal-scan-barrier.py`` extracts the production quiesce callbacks,
serializer invocation and serializer stop. Its pthread model pauses execution
with two earlier FIFO requests outstanding and verifies that quiesce has not
returned. It exercises ordinary dispatch, the recovery cancellation flag,
explicit cancellation, command-init failure, enqueue rejection, an already
stopped serializer and repeated cleanup. The fixture preserves strict stop-step
ordering. Native ASan/UBSan and static big-endian MIPS under pinned QEMU pass.
Queue scheduling, stop/join and scan internals are modeled leaves; the test
does not run a Linux serializer or real scan on the router.

The existing 556-case teardown-order fixture now requires the new helper
between admission closure and DFS-work drain. All 29 driver Python tests pass.
The clean package applies patch 257 and compiles for MIPS. Full-build and exact
image evidence is recorded in ``removal-scan-barrier-results.json``.

Patch 256's earlier source gate was limited to producer admission and copying;
it did not establish failure-safe completion of its downstream barrier. This
audit supersedes that broader interpretation. Hardware boot, real recovery,
DFS/CAC, module unload and RF validation remain outstanding. No factory
container has been rebuilt with patch 257.
