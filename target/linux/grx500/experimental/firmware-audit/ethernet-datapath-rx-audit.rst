Ethernet datapath RX/TX callback audit
=====================================

The GRX500 datapath invokes the Ethernet callback in two distinct modes:
``rx_fn(dev, NULL, skb, len)`` delivers a frame to Linux, while
``rx_fn(NULL, dev, skb, len)`` asks the callback to transmit a redirected
frame.  The imported Ethernet callback implemented only the first mode.  It
freed every valid ``txif`` packet, so the datapath's deliberate TX callback
path could never reach ``dev_queue_xmit``.

Primary-source comparison
-------------------------

The official prpl Foundation Intel Linux ``ugw-8.5.2`` branch archive is
recorded at SHA-256
``88308b69462ab4a664e88718f006717125e8ca1aa3b921853c91f651e2611232``.
Its
``0016-Add-support-for-lantiq-datapath-driver-common.patch`` is SHA-256
``b775f9bb55dfc395654b254425b89b61f0c814669e7998860d90a3e7137c6832``.
That primary source contains both the two-mode caller and an example callback
whose ``txif`` branch assigns ``skb->dev`` and calls ``dev_queue_xmit``.  The
current GRX500 datapath caller independently retains the same two-mode API.

Repair
------

``dp_fp_rx`` now rejects a null skb, negative or undersized callback lengths,
lengths beyond ``skb->len``, and inaccessible PMAC/Ethernet headers.  It trims
any DMA tail beyond the authoritative callback length before removing the
eight-byte PMAC header.  Malformed RX frames update RX error/length counters;
malformed TX-mode frames update ``tx_dropped``.

RX mode now rejects a down interface and returns failure when ``netif_rx``
reports ``NET_RX_DROP`` rather than counting that packet as received.  TX mode
rejects a down interface, assigns the transmit netdev and calls
``dev_queue_xmit``.  ``NET_XMIT_CN`` is accepted as congestion notification;
drops and errors update ``tx_dropped``.  Linux 6.18 documents that
``dev_queue_xmit`` consumes the skb for every return value, so the callback
does not free it again.

The same audit removed Linux 6.18 compatibility warnings adjacent to the
callback.  MAC changes use ``eth_hw_addr_set`` and pass a mutable local copy to
the legacy MAC API.  The pause getter initializes all output fields and marks
the intentional AUTO-to-RXTX fallthrough.  The emulator-only switch-register
helper is now static and compiled only for emulator builds.

Verification
------------

``tests/test-ethernet-rx.py`` extracts the production ``eth_rx`` and
``dp_fp_rx`` functions and compiles them with strict warnings, ASan and UBSan.
Sixteen cases cover null, short, negative and overreported lengths; nonlinear
header pull; trim failure; missing/down interfaces; RX delivery and backlog
drop; RX precedence; and TX success, congestion, drop and errno returns.  The
harness checks exact skb ownership, data offsets, lengths and statistics.

Two additional extracted-function suites cover six MAC-address cases and
sixteen pause get/set cases.  The four focused Ethernet suites pass 45 cases.
All 13 zero-argument GRX500 target scripts also pass, including 252,174
enumerated CBM, MTU, Ethernet, trial and upgrade cases plus the boot-bank
boundary fixture.

A clean MIPS Linux 6.18.55 build links successfully.  The final Ethernet
object contains relocations from ``dp_fp_rx`` to ``__pskb_pull_tail``,
``___pskb_trim``, ``netif_rx`` and ``__dev_queue_xmit``.  A full ``make -j4``
then rebuilds both development images.  Their loader/kernel ELF, DTB,
metadata, rootfs and payload-integrity audits pass, and the packaged MIPS
BusyBox accepts the intact sysupgrade while rejecting independent one-byte
kernel and rootfs corruption.  Exact digests are in
``ethernet-datapath-rx-results.json``.

Boundary
--------

These checks do not execute a packet on the router.  Hardware qualification
must exercise normal LAN/WAN receive traffic, the datapath redirect/TX mode,
nonlinear and jumbo traffic, queue congestion, interface shutdown, and packet
and error counters.  RX checksum offload remains disabled in the AX3000 DT,
so this repair does not claim checksum-engine validation.  No factory
container was rebuilt or approved for upload.
