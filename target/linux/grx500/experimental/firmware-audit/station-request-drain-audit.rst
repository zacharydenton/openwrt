Drain queued station TX requests before radio removal
====================================================

Status: software lifetime barrier and modeled concurrency validation. This
does not establish working Ethernet/Wi-Fi or a safe installation on hardware.

Problem and change
------------------

The preceding async-management fix gives a queued station TX request persistent
cookie storage and an explicit skb owner. Its completion callback still uses
a mac80211 hardware pointer to release rejected packets. Previously, removal
could enter ieee80211_unregister_hw while such a request remained queued.
The hardware TX gate covers the actual submission, not work waiting to enter
that submission, and therefore does not protect this pointer's lifetime.

Each mac80211 owner now has a separate station-request counter, spinlock,
waitqueue and permanent closing flag. The TX entry takes a reference before
validation or asynchronous allocation. Immediate failures release it after
disposing of the packet. An asynchronous request retains it until its own
completion callback finishes packet/context cleanup. Admission failure after
closure uses the ordinary synchronous mac80211 TX-drop path and never queues
a new request.

Radio removal closes and drains these references while core serializers and
recovery state still exist, before wave_rcvry_cleanup_finalize. Unregister also
performs the same idempotent close/drain, covering partial registration rollback
and direct unregister callers. The radio-wide helper tolerates an absent radio
descriptor and unallocated mac80211 owners. Initialization occurs before the
owner is published to the radio module.

The final put wakes waiters under the counter lock. The idle predicate takes
the same lock, so drain cannot return while the final put is still accessing
the owner's waitqueue. No spinlock is held while waiting or invoking the
serializer. The caller must drain from process context outside a counted
request, with serializers able to execute their queued work. The PCI cleanup
call occurs before its later rtnl_lock section. Lifecycle callers must still
serialize unregister itself; the barrier does not make concurrent unregister
calls valid.

This counter is deliberately separate from recovery's hardware TX gate.
Counting queued requests in the latter could make recovery wait for a request
queued behind the recovery task on the same serializer. Recovery does not
close or wait on the new removal-only counter.

Validation
----------

The extended tests/async-management.py executes the actual counter helpers,
TX entry, request completion, core dispatch/handler and unregister wrapper.
In addition to the previous 58 ownership/error cases, it runs 18 concurrent
unregister cases with zero through eight queued requests, cancellation or
lower-layer refusal, rejection after closure, partial completion and repeated
drain/unregister. Unregister's kernel API fixture requires the request count
to be zero. Native ASan/UBSan and big-endian MIPS userspace runs pass. The
old unregister wrapper fails the fixture because it does not close admission;
that run is an ordering assertion, not a reproduced real kernel use-after-free.

The 556-case teardown fixture now executes the real radio-wide drain loop and
checks that each allocated owner is quiesced before recovery-context cleanup
and unregister. It also invokes the NULL-descriptor path. Its per-owner drain
is a model; the separate concurrent suite executes the actual implementation.
Both native and MIPS teardown runs pass. Build/image evidence and input hashes
are recorded in station-request-drain-results.json.

The waitqueue/spinlock model uses pthread synchronization, and serializer
dispatch is controlled by the fixture. This does not execute Linux workqueue
or serializer threads, real mac80211 unregister, firmware or hardware. It
cannot establish scheduler progress if a real recovery task is deadlocked.

Remaining work
--------------

The counted reference ends at asynchronous request completion, not at firmware
TX completion. Accepted packets still owned by BSS rings, IRQ/tasklet frame
and status delivery, scan/control notifications and complete recovery/removal
serialization require further lifetime work before unregister is safe. This
barrier does not independently protect VAP/core objects against individual
interface deletion. General serializer context cleanup after the request's
callback remains governed by its existing serializer lifetime rules.

Station PHY registration remains opt-in. Physical boot, all Ethernet ports,
both radios and complete stock capabilities, peripherals, NAND/power-loss
behavior and reliable serial-free early-hang reset/fallback remain unverified.
The prior factory candidate remains withdrawn; this pass produces development
RAM/sysupgrade artifacts only, not a replacement stock-web upload container.
