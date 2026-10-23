Serializer startup must reject Linux error pointers
==================================================

The prepared WAVE600 source tested ``osdep->thread != NULL`` after
``kthread_run``. The local Linux 6.18.55 ``include/linux/kthread.h`` documents
an error-pointer return on creation failure; ``include/linux/err.h`` defines
the error-pointer range. An error pointer is non-null, so the original check
recorded the worker-start step as successful even though no worker existed.
Queued serializer commands could then wait forever, and the later stop path
could pass the error pointer to ``kthread_stop``.

Patch 258 changes only this success predicate to ``!IS_ERR(osdep->thread)``
and includes ``linux/err.h`` explicitly. Failure returns the existing driver
``MTLK_ERR_NO_RESOURCES`` result. The vendor lifecycle machinery does not mark
THREAD_START complete on failure, so rollback skips ``kthread_stop``. The
outer serializer startup also rolls back before enabling request processing.
The same initialized object remains usable for a later successful start.

Regression evidence
-------------------

``package/kernel/iwlwav-stock/tests/serializer-thread-start.py`` compiles the
entire OS-dependent serializer implementation with the actual
``mtlkstartup.h`` and ``mtlkbfield.h`` headers, retaining their assertions and
step-bit bookkeeping. Only kernel worker/event leaves, type scaffolding and
logging are modeled. A mock stop records invalid pointers instead of
dereferencing them; this detects the unsafe call without crashing the fixture.
The fixture does not run the worker thread or emulate a Linux allocation.

For every error encoding from -1 through -4095 it initializes an object,
injects worker creation failure, verifies the failure result and absence of
an invalid stop, then successfully starts/stops the same object and cleans up
its event. Thus each run covers 4,095 failures and 4,095 successful retries.

The pre-patch implementation fails all 4,095 error cases. Its retained report
is ``serializer-thread-start-before.json``; ``--expect-vulnerable`` makes a
historical reproduction exit successfully but leaves ``source_gate_passed``
false. Without that option the unsafe baseline exits 1. The corrected native
ASan/UBSan and static big-endian MIPS/QEMU runs report zero unsafe failures in
``serializer-thread-start-native.json`` and ``serializer-thread-start-mips.json``.

Run the corrected regression against the prepared source::

  python3 package/kernel/iwlwav-stock/tests/serializer-thread-start.py \
    build_dir/target-mips_24kc_musl/linux-grx500_generic/iwlwav-stock-6.0.8.0.87.0.7

The historical implementation can be reconstructed by reversing patch 258 in
a disposable copy of the prepared source, then running the same test with
``--expect-vulnerable``. Do not reverse patches in the active build tree.
Exact test, source, build and image bindings are recorded in
``serializer-thread-start-results.json``.

Limits
------

This repair prevents false worker-start success; it does not guarantee worker
scheduling, forward progress or real-device recovery. Physical boot, module
load/unload, kernel fault injection, RF/networking, flash and fallback gates
remain open. No factory container was rebuilt with patch 258 and no flash
operation was performed.
