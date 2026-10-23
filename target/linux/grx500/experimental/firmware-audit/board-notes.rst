Stock board configuration audit
===============================

These findings come from the embedded DTB in the official AX3000(US) V1
230831 firmware and its extracted root filesystem. They are static observations,
not a boot or hardware test. TP-Link's V1.60 support page offers these exact
firmware bytes; see ``v16-baseline-audit.rst``. The reference board model string
in the DTB does not independently identify the user's particular v1.6 unit.

``stock-board.json`` records file SHA-256 digests, raw property bytes and DTB
offsets alongside decoded resources. ``board-audit.py`` deliberately preserves
zero-valued cells as bytes instead of guessing whether they are empty strings.
Its simple-bus translation applies every ancestor ``ranges`` mapping.

Reproduce from the OpenWrt repository root, substituting the evidence directory::

  python3 target/linux/grx500/experimental/firmware-audit/board-audit.py \
    /home/zach/code/archer-ax3000-bringup/stock-board-410.dtb \
    --rootfs /home/zach/code/archer-ax3000-bringup/stock-rootfs \
    --sdk-config /home/zach/code/archer-ax3000-bringup/vendor/Iplatform/build/product_configs/ax3000v1/sdk.config \
    --openwrt-dtb build_dir/target-mips_24kc_musl/linux-grx500_generic/image-grx350-tplink-archer-ax3000-v1.dtb \
    --output target/linux/grx500/experimental/firmware-audit/stock-board.json

The decoder's complete raw node/property maps were checked against the Linux
6.18.55 ``dtc`` DTB-to-DTS-to-DTB roundtrip: all 195 stock nodes and all 12
OpenWrt nodes matched. Address translation and interpretation were checked
against the vendor driver bindings below. No stock binaries are included here.

Ethernet
--------

``lib/switch/core_phy.sh`` lines 9–22 supplies the vendor's labelled port order;
the DTB's PHY phandles resolve the corresponding MDIO addresses:

====== ========== ============== ============ ================
Label  Interface  Switch         Switch port  MDIO address
====== ========== ============== ============ ================
LAN1   eth0_4     GSW-L, device0  5            5 on mdio@0
LAN2   eth0_3     GSW-L, device0  4            4 on mdio@0
LAN3   eth0_2     GSW-L, device0  3            3 on mdio@0
LAN4   eth0_1     GSW-L, device0  2            2 on mdio@0
WAN    eth1       GSW-R, device1  15           1 on mdio@1
====== ========== ============== ============ ================

The WAN DT port number is 1. It is not the same namespace as PAE/switch port
15: vendor ``ltq_eth_drv_xrx500.c`` allocates datapath port 15 for a
``lantiq,wan`` interface (line 1315). Physical case numbering is the stock
software's declaration; cable insertion was not observed.

The two switch MMIO bases translate to 0x1c000000 and 0x1a000000. The stock
Ethernet binding is ``lantiq,xrx500-net``. The experimental 4.9-derived driver
matches ``lantiq,xrx500-eth`` instead, so copying the stock node unchanged
would not bind that driver.

``etc/preinit.d/load_gphy_firmware_preinit.sh`` loads the GPHY image through
``/proc/driver/ltq_gphy/phyfirmware``. It configures LAN PHY addresses 2–5 on
device 0 and WAN PHY address 1 on device 1; each receives MMD writes
0x1f01e2=0x70 and 0x1f01e3=0x0b. The five-PHY loader declaration is present in
the DTB. This is a stock initialization sequence, not proof that those LED
writes are necessary to transmit packets. ``etc/init.d/switch`` disables ports
after switch/VLAN/duplex setup; ``etc/init.d/phyport`` later enables them.

PCIe
----

The aliases assign these three controllers. These are declarations of possible
host ports, not proof that all three have endpoints connected.

===== =========== =========== ========== ================ ====================
Alias CSR         Config      MEM window Reset GPIO       Active reset level
===== =========== =========== ========== ================ ====================
pcie0 0x18900000  0xbb000000  0xb8000000 bank 1, line 11  low
pcie1 0x18400000  0xb7000000  0xb4000000 bank 1, line 29  low
pcie2 0x18e00000  0xbf000000  0xbc000000 bank 0, line 14  high
===== =========== =========== ========== ================ ====================

GPIO bank 0 is at physical 0x16c00000; bank 1 is at 0x16c00100. All three
controllers declare a 200 ms reset interval and PHY mode 5, inbound byte swap
1 and outbound byte swap 0. Their PHY reset-controller bits are 12, 13 and 10.
The stock driver uses the separate ``lantiq,rst-high-active`` property for
polarity; ``reset-gpio`` flags are zero even for the active-low ports.
See vendor ``arch/mips/pci/pcie-lantiq.c`` lines 1674–1687 and
``pcie-lantiq.h`` lines 1491–1505. Converting to a modern GPIO descriptor
binding must preserve this polarity rather than copying the flags blindly.

The actual stock PCIe2 GPIO is line 14, not the line 7 found in a generic
reference board. Also, the raw PCIe ``reg`` and parent-side ``ranges`` cells
are relative to ssx3. For example, config cell 0xa3000000 becomes CPU physical
0xbb000000 after adding 0x18000000. The PCI bus address in that same range
remains 0xa0000000; CPU physical addresses and PCI bus addresses are distinct.

Interrupts and queues
---------------------

The stock ``lantiq,gic-grx500`` one-cell interrupts use legacy numbers including
the eight CPU IRQs. Vendor ``arch/mips/include/asm/mach-lantiq/grx500/irq.h``
defines ``MIPS_GIC_IRQ_BASE`` as ``MIPS_CPU_IRQ_BASE + 8``; ``grx500/irq.c``
lines 701–708 initializes that base and installs the identity legacy domain.
The modern GIC shared index is therefore the stock number minus 8. Trigger
types cannot be recovered from these one-cell values alone.

CBM stock IRQs 182, 186, 187, 188, 189 become shared 174, 178, 179, 180, 181.
The manifest retains all 26 dequeue and 15 enqueue table entries. The six
fields are TMU port, TMU queue, DMA controller, DMA channel, port-enable value,
and descriptor count; this follows ``drivers/net/ethernet/lantiq/cbm/cbm.c``
lines 5523–5528. Port-enable values are not simple booleans: preserve them.
DQ2 contains ``2 35 255 255 2 1``. The stock driver explicitly documents
CPU traffic redirected to DQ2 while DQ0 is initialized for freeing buffers
(lines 6079–6084). Copying this topology to a one-CPU kernel without checking
CPU/queue routing and IRQ affinity is not justified.

Memory and current target
-------------------------

The embedded reference DTB declares 480 MiB starting at physical 0x20000000.
The AX3000 product configuration selects 256 MiB DDR. It contains MEM/PHYM
values of 224M but also an ADDMISC boot command that appends
``mem=256M@512M``. Thus the earlier 224 MiB interpretation was incomplete.
The later stock SPL audit in ``bootcore-memory.rst`` resolves this discrepancy:
FMT1=0xfe002e00 maps the auxiliary processor to the upper 32 MiB. The target's
224 MiB Linux map excludes that region. The runtime map remains unobserved.

The initial console-only OpenWrt DTB audited in ``stock-board.json`` contained
no CBM, Ethernet, PCIe, GPIO or GPHY-loader
nodes under any of the checked stock/experimental compatible names. Its 12
nodes described CPU, UART, clocks, interrupt controller, reset and memory.
That historical result explains why the initial image could not support
networking. The integrated target now supplies these board declarations;
``verify-image.py`` audits the compiled image's DTB and required drivers.
A successful kernel link or static image audit cannot validate Ethernet
or Wi-Fi operation on hardware.

These findings do not justify importing the whole reference DTB: RAM differs,
network bindings have changed, old GIC cells have different semantics, PCIe
polarity is carried outside GPIO flags, and CPU queue routing needs adaptation.
