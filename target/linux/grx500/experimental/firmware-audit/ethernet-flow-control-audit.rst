Ethernet datapath flow control and watchdog recovery
===================================================

The GRX500 Ethernet driver registered datapath ``stop_fn`` and ``restart_fn``
callbacks, but both returned success without changing a Linux TX queue. The
datapath API identifies those callbacks as its transmit flow-control boundary.
Consequently, datapath backpressure could not stop packets from entering the
driver. The netdev also advertised a ten-second watchdog while its
``ndo_tx_timeout`` callback was empty, so a genuinely stopped queue had no
driver recovery action.

Repair
------

``dp_fp_stop_tx`` now rejects a null netdev and calls
``netif_tx_stop_all_queues``. ``dp_fp_restart_tx`` rejects a null netdev and
wakes every TX queue only while the interface is running, preventing a late
datapath notification from reopening a device during ``ndo_stop``. The use of
the all-queue helpers also covers the driver's eight-queue PRX300 allocation;
the AX3000/GRX500 allocation currently has one queue.

The timeout callback now increments ``tx_errors``, reports the affected queue,
and wakes all queues. Linux 6.18 invokes it only for a present, running,
carrier-up device with a stopped queue, while holding the netdev TX lock and
temporarily freezing its queues. The wake therefore becomes a bounded
liveness fallback if a datapath restart notification is lost.

Verification
------------

``tests/test-ethernet-flow-control.py`` extracts the three production
functions and compiles them with strict warnings, ASan and UBSan. Seven cases
cover null stop/restart requests, stopping all eight modeled queues, rejecting
a late restart on a down interface, normal restart, eight-queue timeout
recovery and the AX3000 one-queue timeout case. They verify helper call counts,
queue coverage, timeout queue reporting and cumulative TX-error accounting.

A clean ``make target/linux/compile V=s -j4`` rebuilt and linked Linux 6.18.55
for MIPS. The Ethernet object contains relocations to
``netif_tx_stop_all_queues``, ``netif_tx_wake_queue`` and ``netdev_warn``. The
complete GRX500 native test set passes, followed by a full ``make -j4``. Both
development images pass their integrity, loader/kernel ELF, DTB, metadata and
rootfs audits. Packaged MIPS BusyBox accepts the intact sysupgrade archive and
rejects independent one-byte corruption of its kernel and rootfs payloads.
Exact digests are recorded in ``ethernet-flow-control-results.json``.

Boundary
--------

These tests prove the software queue transitions and compiled bindings; they
do not generate real CBM/TMU congestion or execute a netdev watchdog on the
router. Hardware qualification must saturate LAN and WAN traffic, observe
backpressure and recovery without queue wedges, packet storms or silent loss,
and repeat the test during link changes and interface shutdown. No factory
container was rebuilt or approved for upload.
