Ethernet transmit descriptor bounds
====================================

Subsequent status: the software MTU mismatch described below is addressed in
``mtu-audit.rst``. Physical networking and the new buffer mode remain untested.

The CBM CPU enqueue path now accounts for the descriptor's separate byte
offset when checking the packet against its hardware buffer. The descriptor
constructor also rejects lengths exceeding its 16-bit length field. These are
software safety fixes; no physical Ethernet traffic or DMA has been tested.

Reproduced defects
------------------

``setup_desc`` rounds the payload pointer down to an eight-byte boundary and
stores the low three bits in descriptor word 3, bits 23 through 25. The old
``cbm_cpu_enqueue`` bound checked only the aligned pointer and packet length.
A descriptor with a 2,048-byte length and byte offset one was accepted in a
2,048-byte buffer, even though its transfer would extend one byte beyond that
buffer. Both native C execution and emulated big-endian MIPS execution
reproduce this acceptance. Depending on the offset, up to seven excess bytes
could pass the old check.

The new check includes the byte offset before computing the remaining
capacity, rejects malformed unaligned descriptor pointers, and rejects an
invalid range before any DMA cache synchronization or hardware enqueue.
Valid transfers that end exactly at the buffer boundary remain accepted.
Ordinary transmit allocation already checks its copy size; this finding does
not demonstrate that normal 1,500-byte traffic previously failed.

The old constructor also accepted a length of 65,536 and encoded zero in its
16-bit field. A separate MIPS probe reproduces that truncation. The constructor
now refuses oversized lengths without modifying the output descriptor.

Verification scope
------------------

``tests/test-cbm-tx.py`` extracts the actual ``cbm_buffer_dma``, ``setup_desc``
and ``cbm_cpu_enqueue`` functions plus both C descriptor layouts from cbm.h.
Each execution passes 92,178 cases covering every aligned position and all
eight byte offsets in the 2 KiB and 8 KiB fixture buffers. It checks boundary
lengths, representative packet lengths, invalid CPUs/pointers, oversized
lengths, unchanged descriptors on constructor failure, and the sequence of
cache synchronization, barrier and enqueue calls.

Native execution uses ASan/UBSan and the little-endian structure layout.
The MIPS build uses this port's GCC toolchain and runs as a static userspace
program under qemu-mips-static. That execution exercises the target's actual
big-endian C bitfield layout and checks a fixed four-word descriptor example.
The DMA addresses, pool lookup and hardware enqueue are fixtures in both
modes. Neither execution emulates the CBM peripheral, cache coherence,
interrupts or packet transmission, and the fixed descriptor example is not
independent proof of the silicon ABI.

The integrated kernel/image build and static image-content checks are recorded
in ``cbm-tx-results.json``. The prepared CBM source must match this source tree;
the linked kernel and relocation-loader ELFs must match the actual images.
Both images retain the previously verified Wi-Fi fixes and factory-install
protections. No new factory upload container is produced.

Outstanding requirements
------------------------

Physical Ethernet and both radios, complete device behavior, installation,
reset and power-loss recovery remain unverified. The reset gap documented in
``reset-recovery-audit.rst`` is unchanged.

A separate source observation needs follow-up: the GRX500 Ethernet driver
initializes an MTU limit of 9,582, while this target uses 8 KiB CBM buffers.
The GSWIP30 branch of ``dp_get_mtu_size`` returns success without replacing
that limit. This audit does not establish a safe jumbo-frame envelope or
change the configured MTU limit. Buffer overhead and RX/TX hardware limits
must be reconciled before claiming full Ethernet capability.
