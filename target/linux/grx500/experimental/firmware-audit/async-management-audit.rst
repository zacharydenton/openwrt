Asynchronous management TX ownership
====================================

Status: software defects reproduced and corrected. This does not qualify
Ethernet, Wi-Fi operation or installation on physical hardware. No new
stock-web upload container is produced.

Findings
--------

Tracing callbacks during mac80211 removal exposed an earlier lifetime error:
_wv_ieee80211_op_tx passed &cookie, a stack-local variable, inside a copied
mgmt_tx_params structure to the asynchronous serializer. The clipboard copies
that structure, not its pointer targets. A later management submission writes
through the expired pointer. The extracted old code reproduces an 8-byte
stack-use-after-scope write under AddressSanitizer.

The same call supplied no completion callback, so allocation or submission
failure did not return the skb to mac80211. The generic async invocation API
also unconditionally called its optional callback on allocation failure.
The old helper reproduces a null-call crash when that callback is NULL.

Normal BSS completion conditioned station skb reporting on a nonzero status
cookie. Requests carrying IEEE80211_TX_CTL_NO_ACK have cookie zero but still
own their skb. Those packets could survive completion and be overwritten on
descriptor reuse. The low-level frame_drop path also returned success and
could report ACK for a frame it had not queued, without allocating or returning
a valid cookie.

Changes
-------

Station TX allocates a GFP_ATOMIC request context holding the cookie, original
skb and mac80211 hardware pointer. Its completion callback releases an skb
that was not accepted, then frees the context. A new optional internal
mgmt_tx_params ownership slot lets core clear that ownership only after a
successful low-level submission. Every other producer zero-initializes the
request and leaves that slot NULL. The structure is internal to the rebuilt
driver; this is not a firmware or userspace wire-format change.

The ownership slot covers early validation/filtering, serializer cancellation,
disabled ability or scheduling failure, and allocation failure before a
clipboard exists. It avoids double-free if submission succeeded but storing
the request's result later fails. Completion may run before the async call
returns; the caller does not touch the context after invoking it.

The generic error path checks whether the callback is present. BSS completion
now consumes a station skb independently of cookie and processing type, then
clears its descriptor pointer. Existing AP management-cookie/probe reporting
is retained. An unexpected AP-owned skb is released too. Frame rejection
returns MTLK_ERR_NOT_HANDLED and leaves the packet with its caller, without
claiming transmission success or publishing a status with an unset cookie.

Validation
----------

tests/async-management.py extracts the actual mac80211 TX entry, async
invocation/completion helpers, core dispatch callback, full management handler, and frame_drop
branch. Its deferred serializer and allocation/clipboard/firmware leaves run
58 cases covering delayed and immediate completion, cancellation, disabled abilities, malformed
requests, filtering, unknown null-data SID, PMF rejection, lower-layer refusal,
early firmware completion, failure to store a result after acceptance, and
optional callbacks on both allocation failure and completed requests.

Native ASan/UBSan and big-endian MIPS userspace runs pass. The retained old-code
runs fail on the expired stack cookie and null callback respectively. The
updated BSS ownership suite runs 73 cases, including both zero and nonzero
cookies, AP/station, processing type, skb presence and DMA address zero.
The previous concurrent TX-gate suite also passes on native and MIPS userspace.
See async-management-results.json for clean build and image-binding evidence.

These tests do not run the Linux serializer thread implementation, DMA,
mac80211's real packet queues, firmware or radios. They prove the selected
ownership/control-flow behavior under the modeled contracts. Packet callbacks
are modeled consumers; deferred device/VAP destruction is not simulated.

Remaining lifecycle and hardware work
------------------------------------

Linux 6.18.55 ieee80211_unregister_hw explicitly assumes the driver no longer
hands it frames before its internal tasklet is killed and interfaces removed.
The current port still needs complete RX/status callback exclusion and queued
core/scan/recovery-task draining before unregister. This change fixes request
storage and packet ownership; it does not itself keep hw/VAP/core objects alive
against concurrent removal. The asynchronous request context's hw pointer
depends on that outstanding lifecycle work. The subsequent
station-request-drain-audit.rst adds a barrier for queued station TX requests
before radio removal; firmware completion/RX and other lifetime gaps remain.

Station PHY registration remains opt-in (sta_phy); this pass does not claim
station, AP or simultaneous-radio operation. Ethernet, physical boot, complete
stock capabilities, NAND power-loss behavior and serial-free early-hang
reset/fallback remain unverified. The previous factory candidate stays
withdrawn.
