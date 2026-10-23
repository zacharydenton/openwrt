Unpublish the current command before releasing its owner
=======================================================

The serializer worker previously called ``_mtlk_serializer_invoke_command``
before clearing ``current_command``. Invocation ran both the command body and
its completion callback. For ordinary asynchronous requests, the actual core
completion ``_mtlk_core_async_compl_clb`` cleans up the command and frees its
containing execution context. Between that free and the later pointer clear,
``mtlk_serializer_enum_commands`` could pass the freed command to a reader.

This is not restricted to hypothetical API callers. The compiled
``mtlk_df_ui_serializer_dump`` proc callback requests
``WAVE_CORE_REQ_GET_SERIALIZER_INFO``. The core dispatches that request
synchronously, outside the serializer queue. Its enumeration callback reads
the command priority and issuer information. The serializer dump, core
handler, enumeration callback and enumeration API are present in the built
``mtlk.ko`` symbol table. The proc table registers ``serializer_dump`` in the
debug directory; the diagnostic path therefore needs the same ownership
protection as ordinary work.

Correction
----------

Patch 259 passes the serializer to the invocation helper. The helper runs the
command body, then clears ``current_command`` while holding the same lock used
by enumeration. Only after releasing that lock does it call completion.
Readers already holding the lock finish before unpublication; subsequent
readers cannot obtain the command through that pointer. Completion can free
the command or wake its owner without leaving a published reference behind.

The command remains visible during its body, and queued commands retain their
priority/FIFO behavior. Neither the body nor completion runs under the lock.
The worker no longer performs a redundant pointer clear after completion.
This also protects patch 257's stack-owned removal command when its completion
wakes the removing thread. The existing removal-barrier fixture was adjusted
for the helper's new serializer argument; its locking leaves remain modeled.

Regression and evidence
-----------------------

``tests/serializer-current-lifetime.py`` extracts the actual enqueue, worker
loop, invocation and enumeration functions, plus the actual core completion.
It supplies intrusive-list and remove-lock leaves and uses pthread mutexes
for serializer locking. Two heap-owned commands are enqueued at different
priorities. During each command body, enumeration sees the live current
command and any remaining queued work. Early reader termination is checked.

The core completion performs a real free, then a condition-variable rendezvous
pauses it. A second thread enumerates at that exact point before allowing the
worker to continue. The reader compares numeric addresses against freed
addresses before accessing fields: the baseline demonstrates stale publication
without deliberately dereferencing freed memory. It observes two freed
commands before the patch and zero afterward. Both commands finish once, the
pending count drains, and final enumeration is empty.

The baseline report is ``serializer-current-lifetime-before.json``. Its
``source_gate_passed`` remains false even when ``--expect-vulnerable`` allows
historical reproduction to exit 0; ordinary baseline execution exits 1.
Corrected native ASan/UBSan and static big-endian MIPS/QEMU results are in
``serializer-current-lifetime-native.json`` and
``serializer-current-lifetime-mips.json``. Exact source, test, build and image
bindings are in ``serializer-current-lifetime-results.json``.

Run the corrected test against the prepared source::

  python3 package/kernel/iwlwav-stock/tests/serializer-current-lifetime.py \
    build_dir/target-mips_24kc_musl/linux-grx500_generic/iwlwav-stock-6.0.8.0.87.0.7

For historical reproduction, reverse patch 259 only in a disposable source
copy and add ``--expect-vulnerable``. Do not alter the active prepared tree.

Limits
------

This fixture controls a valid interleaving but does not run a kernel worker,
spinlock, procfs read or firmware on the router. Real diagnostic reads under
traffic/recovery, module unload, boot, RF/networking, flash and fallback remain
unverified. No factory container includes patch 259 and no flash write was
performed.
