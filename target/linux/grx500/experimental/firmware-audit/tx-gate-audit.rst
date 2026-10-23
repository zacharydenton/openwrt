Data and management TX exclusion during recovery
==============================================

Status: software concurrency and build checks only. No router boot, Ethernet
traffic, radio traffic, NAND installation or serial-free fallback was tested.
This change does not qualify a stock-web upload image.

Problem and change
------------------

IRQ/tasklet draining does not stop a process or network TX callback that has
already borrowed a descriptor. The data and public management TX entry points
now acquire a per-hardware gate before entering their existing submission
bodies, and release it on every return. Recovery closes the gate and waits
for accepted submissions before draining interrupts or freeing rings. Failed
restore leaves it closed; successful restore opens it after hardware reaches
READY. Initial startup opens it at MMB_MAC_EVENTS_START, after calibration.
Removal permanently closes it before recovery-context cleanup and mac80211
unregister. A subsequent recovery resume cannot undo permanent closure.

The spinlock protects admission, outstanding-user count and the permanent
stop latch. Enter/exit can run in atomic context. The last exit wakes waiters
while holding the lock, and the drain predicate acquires that same lock: drain
cannot return while the last exit still accesses the waitqueue. Closing and
waiting require process context, outside an accepted TX transaction. Normal
recovery transitions still depend on caller lifecycle serialization.

The data wrapper covers descriptor borrowing, mapping, submission, rejection
and release. The management wrapper preserves its caller's packet ownership
when admission fails. Low-level management resend from a completion tasklet
remains covered by IRQ/tasklet draining. The optional DirectConnect dispatch
inside the data wrapper is covered, but independently owned accelerator
producers have not been verified by this change.

Reset initiation
----------------

TX validation errors can request MTLK_HW_RESET. The previous property handler
called wave_rcvry_task_initiate synchronously. Its scheduling path takes
recovery mutexes, creating a possible dependency between a counted TX caller
and recovery waiting for that caller to leave. Reset requests now schedule a
per-hardware work item; the property return means request acceptance, not
recovery completion. Pending requests coalesce using workqueue semantics.

Enqueue and permanent closure share the gate lock. This prevents a requester
that passed the stopping check from enqueueing after removal's cancellation.
Permanent stop drains TX and calls cancel_work_sync before destroying the
recovery context. The worker rechecks stopping and halted state. A worker
already past those checks may complete initiation while stop waits for it;
its separately scheduled recovery tasks are NOT covered by cancel_work_sync.
Full recovery-task/removal synchronization remains required.

Validation and limits
---------------------

tests/tx-producer-gate.py extracts the actual gate helpers, reset request and
worker, and both entry wrappers. It runs 72 concurrent scenarios combining
zero through eight accepted producers, both entry types, success/error
returns, and temporary/permanent closure. It checks rejection during closure,
waiting for accepted producers, reopening, permanent-stop behavior, argument
forwarding and management-packet ownership on refusal.

Additional cases exercise deferred reset from an accepted transaction,
coalesced pending work, halted-state rejection at request and dispatch,
pending cancellation, and waiting for a running reset worker while cancelling
a pending follow-up. These use pthread spinlock/waitqueue/workqueue models.
The reset fixture deliberately drains producers to test the dependency that
made synchronous initiation unsafe. It does not run the real recovery scheduler.

The updated recovery fixture checks that reset occurs with producers closed,
success reopens them and failures do not. It retains 164 IRQ lifecycle and
168 restore/failure/retry cases per DCDP_SEPARATE_REG variant (two variants).
The 556-case teardown fixture also runs with the new stop call, but models
that call; only the dedicated TX test executes the actual gate implementation.

Native ASan/UBSan and big-endian MIPS userspace runs pass. These are not Linux
lockdep/KCSAN tests, a running kernel, DMA, firmware execution or RF evidence.
See tx-gate-results.json for build and image-binding results and input hashes.

Remaining work
--------------

The gate does not protect the lifetime of a VAP/core before a wrapper reaches
it. Asynchronous scan/control/recovery tasks, complete removal serialization,
and frame/status callbacks across mac80211 unregister still need auditing.
Physical boot and all Ethernet ports, simultaneous radios and stock feature
coverage remain unverified. No software fixture establishes NAND power-loss
behavior or a reliable reset/fallback after an early boot hang. The previous
factory candidate remains withdrawn; no replacement factory container is
produced by this change.
