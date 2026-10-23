Read-only factory NAND access
=============================

``grx500-calibration.c`` implements the AX3000 V1 EBU NAND read path with
Linux 6.18's exec_op API. It is a calibration reader, not a flash-upgrade
driver. The driver and the software BCH dependency compile and link in the
experimental GRX500 kernel; the DTS compiles. Physical flash reads and ECC
results remain untested on hardware.

Integration:

* Copy ``files/`` into the target overlay or prepared kernel.
* Source ``Kconfig.nand`` from the target architecture Kconfig.
* Add to drivers/mtd/nand/raw/Makefile::

    obj-$(CONFIG_MTD_NAND_GRX500_CALIBRATION) += grx500-calibration.o

* Include ``grx500-calibration.dtsi`` in the AX3000 board DTS after grx500.dtsi.

The stock DTB enables ``gen_nand, lantiq,nand-xway`` at physical 0x17c00000,
with EBU registers at 0x16f00000. It contains no enabled DMA-NAND compatible
node. Although the product kernel also compiles a DMA NAND driver, that driver
does not match this node. The PIO path is therefore the relevant source.

Product kernel.config selects LTQ_BCH_MODE and LTQ_BCH_4BITS. The corresponding
stock xway_nand.c sets software BCH with 512-byte steps and seven ECC bytes;
stock nand_bch.c initializes m=13,t=4 and places ECC at the OOB tail. Linux
6.18's software BCH uses the same parameters and layout. A 2048-byte page
with 64-byte OOB therefore uses ECC bytes36–63, preserving the first two
bad-block marker bytes. Detected bus width/page/OOB geometry is checked.

The calibration offset 0x1c0000 and size0x100000 agree between the stock DTB
and product U-Boot mtdparts. Only this partition is registered, and both
the master MTD and its partition have MTD_WRITEABLE cleared. The optional
block interface uses MTD_BLOCK_RO. Before accessing any controller register,
exec_op rejects every operation containing data-out or a command outside its
read/read-ID/status/reset/get-features whitelist. Program, erase, feature
updates and vendor commands cannot reach the chip. Bad-block scanning uses
the core's in-memory table; no flash BBT is requested.

EBU command/byte-transfer polls have 1 ms timeouts; NAND ready waits are
sleepable and bounded to at most 1 second. Clock failure, scan failure,
transfer timeout and uncorrectable ECC propagate as errors. Existing U-Boot
NAND pinmux is preserved, matching the stock reference's reserved-pad policy.

The controller does not implement setup_interface. Linux 6.18 therefore keeps
the default mode-0 timings without issuing SET_FEATURES from
nand_reset_interface/nand_setup_interface. Micron's optional on-die ECC probe
treats rejected SET_FEATURES as unsupported and continues with software ECC.
The NAND manufacturer's actual ID and any manufacturer-specific requirements
still need hardware verification.

Factory calibration extraction
------------------------------

The target's ``base-files/lib/preinit/81_grx500_calibration`` runs before the
normal boot init script loads modules. It requires the OpenWrt ``nand-utils``
package. It reads the calibration character device with::

    nanddump --quiet --bb=skipbad --omitoob --file /tmp/... /dev/mtdN

ECC remains enabled. A complete successful dump is required before parsing;
uncorrectable read errors abort extraction. Character and block MTD devices
alone preserve physical offsets and do not skip bad blocks.

These flags reproduce the actual stock utility, not assumptions about a
generic nanddump version. The extracted stock nanddump identifies itself as
1.4.6. Its ELF file offset 0x7000 (virtual address 0x417000) contains the
big-endian value 2 for the bad-block enum, followed by 0x01 at offset 0x7004
for omitoob. Direct Ghidra decompilation of main at 0x400c0c shows skipbad
selecting enum2, advancing over marked blocks without output, and skipping
the OOB output branch when that byte is nonzero. Its BSS noecc byte is zero;
the normal path queries ECC statistics. This corroborates its embedded help.
The direct Ghidra fallback is static evidence, not a REA Evidence record or
an execution of the MIPS binary.

Stock ``usr/sbin/vol_mgmt`` read_calibration (around line494) pipes nanddump
into tar to extract ``wlanconfig.gz``. The outer NAND container is therefore
a gzip tar holding another gzip tar. ``lib/wifi/tplink_intel.sh`` wifi_init
calls read_img wlanconfig, then extracts the inner archive before loading the
radio modules. Static read_img/call-site analysis corroborates this chain.

The preinit helper accepts exactly one regular-file container member and one
regular file for each ``cal_wlan0.bin`` and ``cal_wlan2.bin``. It writes tar
payloads to fixed temporary filenames, verifies the inner gzip CRC, checks
both EEPROM sizes against the imported driver's 256–2048-byte bounds, then
copies only those two files to /lib/firmware. Erased NAND padding after the
outer gzip stream is allowed. Failed extraction leaves no radio calibration
files; it does not invent calibration or modify flash. The driver subsequently
validates the EEPROM format. No real per-device dump was available for testing.

``test-calibration.py`` exercises nine nested archive cases, including NAND
padding, optional ./ names, duplicate/missing files, symlinks, invalid sizes
and corrupt inner CRC. All pass with GNU tools and host BusyBox 1.36.1::

    python3 target/linux/grx500/experimental/nand/test-calibration.py
    python3 target/linux/grx500/experimental/nand/test-calibration.py \
        --busybox /usr/lib/initcpio/busybox

The target BusyBox 1.38 configuration enables tar, gzip with decompression and
integrity testing, awk, wc and mktemp. Its MIPS executable was not run on the
host. The fixtures test the actual shell parser, not NAND I/O or radio operation.

Stock file SHA-256 values (official 230831 firmware):

* nanddump: 2fe60e7ac958a1853c89a8d9f4863a2112239ce857d1e06823e233d9aed27592
* vol_mgmt: 7ea7ec9dd7326b346d22909d1051de517d13d38f5778144c48168021265e8208
* tplink_intel.sh: 74c6abb7b032784712736ac24a7425fc3c450868dd4621ab118a3923c7896438

The full link test used an empty initramfs to avoid coupling to the concurrent
OpenWrt rootfs build. It is a kernel integration check, not a bootable deliverable.
``build-results.json`` records the exact driver/kernel hashes and test scope.
