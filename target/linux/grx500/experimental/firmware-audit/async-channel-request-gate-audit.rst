Asynchronous channel requests could cross Wi-Fi teardown
=========================================================

The prepared WAVE600 source contains eight calls to
``_mtlk_df_user_invoke_core_async``.  The DirectConnect multicast producer is
compiled out in this build, leaving seven MIPS call sites.  Management TX has
its own request owner and teardown drain, operating-mode updates are copied
values, the statistics callback is ordered behind its synchronously cancelled
timer and serializer lifetime, and the scan/CAC timeout requests have no
borrowed payload.  Two remaining ``WAVE_RADIO_REQ_SET_CHAN`` submissions were
different: each copied a raw master ``struct net_device *`` into a clipboard
that the core serializer could consume later.

One producer is ``_mtlk_core_switch_channel_normal``, reached when a station
receives the first beacon after a DFS channel change.  The other is the
serialized CAC-timeout handler.  The latter checked ``removal_pending`` before
building its request; the former did not.  A flag check alone was insufficient
in either case: teardown could set the flag and queue its synchronous scan
barrier after a producer passed the check but before that producer submitted
its asynchronous channel request.  The request could then run after the
barrier and use the netdev for a cfg80211 notification while mac80211 teardown
was unregistering it.

Source-level correction
-----------------------

Follow-up: ``removal-scan-barrier-audit.rst`` reproduces failures of the ordinary
user request used as the downstream barrier below. Patch 257 replaces that
fallible request. Patch 256 alone proves producer admission/copy ordering, not
failure-safe completion before unregister.

Patch 256 adds a small channel-request admission gate to each radio's scan
support.  A spinlock protects the existing removal flag and an in-flight
producer count.  Both asynchronous ``SET_CHAN`` producers must enter the gate
before copying and submitting their request and leave immediately after
``_mtlk_df_user_invoke_core_async`` returns.  That function copies the complete
``set_chan_param_data`` into its clipboard before returning.

``scan_support_prepare_remove`` closes admission under the same spinlock,
releases the radar wait, synchronously cancels the CAC and scheduled-scan
timers, and waits for every producer admitted before closure to finish its
clipboard copy.  ``wave_radio_scan_quiesce`` then issues the pre-existing
synchronous master-serializer abort/prevent request.  Because no later channel
producer can enter, that request is a real barrier: all copied pre-close
``SET_CHAN`` work is ahead of it and completes while both wiphys and the master
netdev still exist.

The gate deliberately covers only asynchronous channel-request production.
It does not retain a netdev past unregister or permit a late cfg80211 callback;
both would preserve memory while still violating interface teardown ordering.

Verification
------------

``tests/async-channel-request-gate.py`` extracts the actual gate helpers,
teardown function and normal channel-switch producer from the prepared source.
It also requires enter/submit/exit ordering in the actual CAC handler.  A
pthread harness checks ordinary request copying, post-close rejection, and a
deterministic race in which teardown must wait for a producer stopped inside
the asynchronous copy.  Its rendezvous uses C11 atomics and the extracted gate
uses a pthread mutex model for the kernel spinlock.  The harness passes with
native ASan/UBSan and as a statically linked big-endian MIPS binary under the
pinned QEMU executable.

The extended ``tests/scan-cancel.py`` extracts the same helpers and passes all
21 scan-cancel, timer and serializer cases.  All 28 Python driver test programs
and the standalone HE packing test pass.  All 15 zero-argument GRX500 programs
pass, covering 252,192 enumerated cases plus 14 trial, 8 trial-worker and 9
upgrade-policy cases.  The clean Wi-Fi package, integrated Linux target and
full development build pass.  Both rebuilt images pass loader/ELF, DTB,
metadata and rootfs audits; packaged MIPS BusyBox accepts the intact sysupgrade
and rejects independently corrupted kernel and rootfs members.

Exact patch, test, prepared-source, object, module, package, image and report
digests are recorded in ``async-channel-request-gate-results.json``.

Hardware boundary
-----------------

No Archer AX3000 was available.  These tests do not execute a real beacon/CAC
race, firmware channel switch, cfg80211 notification, module removal, recovery,
RF traffic, physical boot, flash write or stock-bank fallback.  No factory
container was rebuilt with patch 256, and no retained stock-web candidate is
approved for upload.
