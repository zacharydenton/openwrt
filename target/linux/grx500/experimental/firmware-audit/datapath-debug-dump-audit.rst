GRX500 datapath debug-dump bounds audit
=======================================

Status
------

The GRX500 datapath passed raw ``skb->data`` pointers to a dumper that indexes
contiguous memory. One RX error path selected the larger of ``skb->len`` and
``dp_print_len``; it therefore requested bytes beyond the packet whenever the
two values differed. Other RX and TX diagnostic paths bounded the raw pointer
with total ``skb->len``, which includes nonlinear fragments that are not
contiguous with ``skb->data``.

The shared ``dp_skb_dump_len`` helper now derives every raw skb dump length
from ``skb_headlen()``. It rejects exhausted or out-of-range offsets and treats
a positive ``dp_print_len`` as a cap. A zero or negative limit preserves the
historical full dump for an ordinary linear packet, while a nonlinear packet
stops at the end of its linear head. Fixed-size PMAC dumps remain protected by
the receive path's earlier header linearization.

Affected paths
--------------

The correction covers:

* the initial RX packet dump;
* the rate-limited zero-port RX error dump;
* the post-parser RX Ethernet-data dump; and
* the common TX packet dump.

This is diagnostic code, but the unsafe paths run in packet context after a
debug flag or zero-port error enables them. Diagnostics must not turn an
otherwise recoverable malformed descriptor or nonlinear skb into a kernel
memory over-read.

Source provenance and test
--------------------------

The relevant official source is the ``ugw-8.5.2`` archive, SHA-256
``88308b69462ab4a664e88718f006717125e8ca1aa3b921853c91f651e2611232``.
Its coding-style patch
``ugw_linux_patches/0738-DRVLIB-SW-2625-Fix-DP-module-coding-style-with-code-.patch``
has SHA-256
``8d53317cf579a79dc7dfc671d84367898fb788e554f40b50ae1c7b99735a7bfd``.
That patch introduces a capped initial RX length but retains the larger-value
zero-port expression and total-length TX behavior. The OpenWrt adaptation now
uses one explicit linear-head contract for all four locations.

``tests/test-datapath-debug-dump.py`` extracts the exact inline helper from
``datapath.h``. It compiles with ``-Wall -Wextra -Werror`` and ASan/UBSan, then
passes 11 cases covering uncapped and negative limits, smaller/equal/larger
caps, offsets inside/at/beyond the head, and a 4,096-byte logical skb backed by
only 64 linear bytes. The harness reads every returned byte so an oversized
result reaches the sanitizer redzone. It also verifies structurally that the
three RX sites and one TX site use the helper and that the old total-length
expressions are absent.

MIPS and image validation
-------------------------

``make target/linux/compile V=s -j4`` cleanly rebuilt Linux 6.18.55 for
``mips_24kc``. The copied header and both copied source files match their
target inputs byte for byte. ``datapath_rx.o`` is 47,488 bytes with SHA-256
``c064ff24e5fb75eb1ed188a89bfb914b1363fbffe9e8ef9db83caa7eac7317c9``;
``datapath_tx.o`` is 31,268 bytes with SHA-256
``12f40190b772cb00fb76f9dfb83804c0f1626fac2d9a3a2426664f27a5b20eef``.
Their disassembly subtracts skb ``data_len`` from total length before each raw
dump, checks offsets, and applies a positive limit with an unsigned minimum.

All 15 zero-argument GRX500 scripts pass: 252,192 enumerated cases plus the
boot-bank parser boundary test. A subsequent full ``make -j4`` build passes.
The rebuilt initramfs and sysupgrade images pass their integrity,
relocation-loader/kernel ELF, DTB, metadata and rootfs audits. Packaged MIPS
BusyBox accepts the intact sysupgrade archive and rejects one-byte corruption
of either payload.

Hardware boundary
-----------------

No router executed these debug paths. Hardware testing should enable bounded
RX/TX data diagnostics with linear and nonlinear traffic, inject or observe a
zero-port descriptor error, and confirm useful output without a fault or
console starvation. These checks do not establish boot, networking, RF,
flash safety or stock-bank fallback.
