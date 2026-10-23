Built AX3000 network device-tree comparison
===========================================

``verify-network-board-dtb.py`` compares the built GRX350/AX3000 DTB with
the pinned AX3000(US) V1 230831 stock DTB and the stock switch-port script.
It checked 221 values in the rebuilt DTB, including PCIe controller windows,
resets, IRQs and GPIO polarities; CBM MMIO and IRQs; both switch bases; four
switch DMA engines, DMA0 and DMA3/4; labelled LAN/WAN ports and PHY addresses;
GPHY resets; and the Linux RAM span. Eight deliberate corruptions were rejected. The result
and image digests are in ``network-board-bindings.json``. Both image audits
bind the same rebuilt DTB and validate the corresponding image/ELF pair.

The comparison exposed stock DMA settings that the previous DTB did not
match. DMA1 TX now uses descriptor SRAM, polling count 108 and LAB count 2;
DMA1 RX disables byte-enable; DMA2 RX declares the stock descriptor-SRAM
value. ``hdma.c`` programs the DMA1 TX descriptor-path bit and the RX
byte-enable bit from those properties. Its current descriptor-path helper
ignores DMA2 RX, so that property is documentary until the driver supports
it. The source and rebuilt DTB now carry all stock-present properties for the
four switch DMA engines, including their translated IRQs.

The stock DTB declares DMA0 at 0x16e00000, DMA3 at 0x1e300000 as active,
and DMA4 at 0x1e400000 as disabled. DMA0 serves SPI/NAND/memory-copy; DMA3
serves TOE/memory-copy. The current DTB now declares all three with the stock
aliases, MMIO, IRQs and properties. The imported DMA driver now matches the
stock-specific DMA0 compatible. DMA4 remains disabled. The current NAND
driver uses programmed I/O and does not call DMA0, so DMA0 presence does not
establish NAND-DMA use.

The pinned TP-Link GPL archive ``ax3000v1_GPL_3.tar.gz`` has SHA-256
``de5befc72e4198e490ff4205439d4f8407175f92e487afc44071fd5a726be4c6``.
Its ``linux-3.10.104-sources/arch/mips/lantiq/grx500/sysctrl.c`` has SHA-256
``1f77041054f39e73e31092e3fa6742dc4f1df94dc283475d768ff8821ac94ee3``.
That source maps DMA0 at 0x16e00000 to CGU gate bit 5 and DMA3/TOE at
0x1e300000 to bit 22 (the latter in lines 317-318). The current clock
provider now registers both gates; ``clock-audit.py`` binds the resulting
DTB references to their IDs and verifies the gate records inside both linked
kernel images. Mutating either gate bit is rejected. This is clock-binding
evidence, not proof that the engines transfer data on this board.

No TOE or hardware-acceleration performance claim follows from the DMA3
declaration: the default networking path still uses software forwarding.

These are static prerequisites. The hardware is still untested: a passing
comparison cannot prove PCIe enumeration, any Ethernet link or packet path,
both Wi-Fi radios, or safe stock-web installation. The current images are
development RAM/sysupgrade artifacts, not stock-web upload files.

Reproduce after extracting the pinned stock image and building OpenWrt::

  python3 target/linux/grx500/experimental/firmware-audit/verify-network-board-dtb.py \
    --stock-dtb /path/to/stock-board-410.dtb \
    --stock-switch-script /path/to/stock-rootfs/lib/switch/core_phy.sh \
    --openwrt-dtb build_dir/target-mips_24kc_musl/linux-grx500_generic/image-grx350-tplink-archer-ax3000-v1.dtb \
    --initramfs-report /path/to/integrated-safety-initramfs.json \
    --sysupgrade-report /path/to/integrated-safety-sysupgrade.json \
    --negative-controls --output /path/to/network-board-bindings.json

The verifier pins both stock input hashes. The two image reports are produced
by ``verify-image.py`` and ``verify-sysupgrade.py`` for the exact rebuilt
artifacts; passing their paths binds this board comparison to those images.
