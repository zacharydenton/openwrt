GRX500 datapath RX callback-result accounting audit
===================================================

Status
------

The GSWIP 3.0 receive path previously ignored every registered RX callback
return value. It incremented a receive-success counter after normal RX, a
transmit-success counter after redirected TX, and an LCT-success counter after
an LCT clone even when the callback reported failure. The callback had already
consumed the skb, so retrying or freeing it in the datapath would have created
an ownership error.

``datapath_rx.c`` now routes its four callback sites through one helper. A
``DP_SUCCESS`` result selects exactly one success counter. Any nonzero result
selects ``rx_fn_dropped`` and the global ``rx_drop`` counter instead. This
covers normal RX, redirected TX, LCT multicast/broadcast clones and LCT
unicast delivery. The datapath neither retries nor frees a callback-owned skb.

Return and ownership boundary
-----------------------------

The registered callback type returns ``int32_t``. The AX3000 port callback is
``dp_fp_rx``; its receive and transmit branches consume the skb on success and
on every error. The GRX500 CQM producers pass ownership to ``dp_rx`` and ignore
its return. Returning the callback failure from this layer would therefore not
make a retry safe.

The outer receive API continues to return ``DP_SUCCESS`` after it has handled
the packet. This matches the later official UGW 8.5.2 receive-API restructure,
whose ``_dp_rx`` comment says that it always returns success because errors are
handled internally. That source still increments the success MIBs without
examining the callback result; it establishes the outer return/ownership
contract, not correct result accounting.

Source and extracted test
-------------------------

The production source is
``files/drivers/net/datapath/dpm/gswip30/datapath_rx.c``. Its SHA-256 is
``a16b32aa79e1f6f009591ab1cbda1282e0f052da46ed2c6f559d2bb59b2ac73d``.
The official comparison is the ``ugw-8.5.2`` archive, SHA-256
``88308b69462ab4a664e88718f006717125e8ca1aa3b921853c91f651e2611232``;
the relevant restructure is
``ugw_linux_patches/1587-DRV-DPM-SW-430-DPM-restructure-rx-APIs.patch``,
SHA-256
``b4248aa824e2ab4b23322e97722d0d0c45213e30cae0a30a6306e2e769a631cb``.

``tests/test-datapath-rx-accounting.py`` extracts the exact helper body from
the production source and compiles it with native GCC, ``-Wall -Wextra
-Werror`` and ASan/UBSan. Seven cases pass:

* normal RX success;
* normal RX negative failure;
* normal RX positive, nonzero failure;
* redirected TX success and failure; and
* LCT clone success and failure.

Each case verifies the callback arguments, exactly one callback consumption,
and mutually exclusive per-subinterface/global success or drop counters. The
positive nonzero control prevents an accidental ``< 0``-only interpretation
of the callback contract.

MIPS and image validation
-------------------------

``make target/linux/compile V=s -j4`` rebuilt Linux 6.18.55 for
``mips_24kc``. The copied build source matches the target source byte for
byte. ``datapath_rx.o`` is 47,488 bytes with SHA-256
``c064ff24e5fb75eb1ed188a89bfb914b1363fbffe9e8ef9db83caa7eac7317c9``.
Its MIPS disassembly contains the callback-result branch and distinct atomic
and per-CPU updates for RX success, TX success, LCT-clone success and failure.
The object has four ``R_MIPS_26`` call relocations to that helper, matching the
four production delivery sites.

All 15 zero-argument GRX500 test scripts pass: 252,192 enumerated cases plus
the boot-bank parser boundary test. A subsequent full ``make -j4`` build
passes. The rebuilt initramfs and sysupgrade images pass their independent
integrity, relocation-loader/kernel ELF, DTB, metadata and rootfs audits. The
packaged MIPS BusyBox checksum test accepts the intact sysupgrade archive and
rejects one-byte corruption of either payload.

Hardware boundary
-----------------

No AX3000 hardware executed this change. Physical testing must generate both
normal RX and redirected TX success/failure, exercise LCT if enabled, and
compare the datapath MIBs with Linux interface counters under congestion,
interface shutdown and link transitions. These checks do not establish boot,
Ethernet forwarding, RF operation, flash safety or stock-bank fallback.
