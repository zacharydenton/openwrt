Intel GRX500 / TP-Link Archer AX3000 bring-up
==========================================

Status
------

Experimental device port for TP-Link Archer AX3000(US) V1, including
hardware v1.6. The scope includes Ethernet, both radios, flash installation,
persistent settings, USB, LEDs and buttons. No router has booted this image
during development. Compilation, tests and firmware comparison do not
establish working hardware or measured throughput.

The one-upload installation is unfinished. The original retained images have
a reproduced decompression overlap at the stock flash-loading address and
must not be installed. The current build adds an experimental relocation
loader; isolated decoding passes, but its hardware handoff is untested.
See ``experimental/firmware-audit/one-shot-audit.rst`` and the opt-in first-boot
implementation in ``experimental/firmware-audit/factory-trial-audit.rst``.
No hardware-validated factory upload image is provided.
The dynamic AP add/delete path previously crossed RTNL from a waiting ioctl
thread to a serializer kthread and freed VAP resources before removing their
published lookup entry. Patches 246-249 address that source-level defect,
the resulting cfg80211 wiphy-lock dependency and a VAP creation rollback leak.
This remains untested on a router;
see ``experimental/firmware-audit/vap-rtnl-lifetime-audit.rst``.
Patch 254 closes the known station ``remove_interface`` terminal lifetime
paths at source level: failed deletion unpublishes and detaches the VIF, while
an independently owned VAP/netdev reference is retried by a cancellable worker
or released by final VAP-manager teardown. The extracted ASan/UBSan cases and
all 26 driver host tests pass, and the MIPS package links. Real recovery,
Fresh development initramfs and sysupgrade images also pass their static
integrity, ELF-binding and rootfs audits. Real recovery, workqueue scheduling
and interface removal remain untested on the router; see
``experimental/firmware-audit/station-remove-terminal-audit.rst``.
The earlier experimental factory candidate has been withdrawn: its automatic
commit could accept link/radio enumeration without working networking. Current
factory source requires an explicit root acceptance command during a timed
trial, after a person has tested the device. That manual step does not prove
working hardware or make an upload safe. See
``experimental/firmware-audit/network-acceptance-audit.rst``. These source fixes
are not present in the retained historical images.
The current development kernel also lacks a hardware watchdog; an ordinary
trial-worker reboot cannot recover a hard lockup or an early boot hang.
The shipped stock kernel's extracted configuration disables its Linux
watchdog too, so generic SDK watchdog patches are not evidence of working
stock recovery. See ``experimental/firmware-audit/reset-recovery-audit.rst``.

Implemented in the target and its selected packages:

* GRX350/GRX500 MIPS startup, vendor EVA mapping, four Linux VPEs, GIC,
  timer, clocks, ASC serial console and reset.
* GSW-L/GSW-R, CBM/TMU, DMA, datapath, five Ethernet PHYs and stock GPHY
  firmware. Explicit switch rules keep LAN and WAN traffic isolated until
  Linux forwards it. Shared hardware queues have SMP locking.
* All three stock PCIe links, their PHYs, resets and GPIOs.
* Native Linux 6.18 adaptation of the matching WAVE600 driver and firmware:
  HT/VHT/HE, contiguous 160 MHz, SAE/WPA3 and protected management frames.
  Hostapd uses native nl80211 rather than the vendor's private AP startup.
  Per-device calibration is extracted before wireless module autoload.
* Factory LAN MAC retrieval from the named stock data volume, with the stock
  lower-24-bit increment for WAN. No shared vendor fallback address is used.
* BCH4/512 NAND, protected bootloader/environment/calibration partitions,
  stock A/B volume-name root selection, and staged atomic UBI upgrades.
* USB1 DWC3/xHCI host, PHY, power and overcurrent recovery; mass storage,
  UAS, FAT, exFAT, ext4 and NTFS support.
* Power, LAN, WAN and USB LEDs; reset, LED toggle, and the combined WPS/radio
  button. A short release requests WPS; holding at least two seconds toggles
  the radios.

Radio firmware scheduling and physical behavior remain hardware tests.
The default image uses software packet paths. An optional DirectConnect
ring/UMT transport variant is included under ``experimental/directconnect``;
its README describes the separate build and activation procedure. Stock
PPA/MPE acceleration and throughput have not been reproduced. The stock firmware does not support
80+80 MHz or TWT, so those capabilities are not advertised. USB1 is selected
from the stock USB LED and board wiring evidence; the external connector
mapping still needs physical confirmation. USB0 conflicts with a PCIe reset
pin and is not enabled.

The rebuilt DTB now matches the stock DMA0, four switch DMA engines, active
DMA3 TOE/memory-copy controller and disabled DMA4 declaration. The linked
kernel clock tables include the stock DMA0 and TOE gate bits. The 221 static
board-wiring checks in
``experimental/firmware-audit/network-board-audit.rst`` do not prove traffic.

Ethernet now uses the vendor driver's 8,000-byte maximum MTU and the existing
16 KiB jumbo-buffer mode, with explicit Linux netdev limits. The 8 MiB jumbo
pool is unchanged, so nominal jumbo-buffer count is halved. Physical jumbo
traffic and performance remain unverified; see
``experimental/firmware-audit/mtu-audit.rst``.
The subsequent ``experimental/firmware-audit/mtu-switch-audit.rst`` corrects
the CPU-facing switch frame-length settings and propagates MTU register API
errors; register fixtures pass, but physical jumbo traffic remains untested.
The PHY-backed ethtool restart callback now delegates to Linux phylib instead
of returning false success without restarting negotiation. Extracted sanitizer
tests, the target kernel, both development images and their static audits pass;
real link renegotiation remains a hardware test. See
``experimental/firmware-audit/ethtool-autoneg-audit.rst``.
The registered datapath TX flow-control callbacks now stop and conditionally
restart every Linux transmit queue instead of returning false success, and the
netdev watchdog records and recovers a stalled queue. Seven extracted
sanitizer cases, the full GRX500 native suite, the linked MIPS kernel and both
rebuilt image audits pass. Real congestion, watchdog and shutdown races remain
hardware tests; see
``experimental/firmware-audit/ethernet-flow-control-audit.rst``.
The datapath's second RX-callback mode now hands redirected packets to the
Linux transmit path instead of freeing them. Callback lengths, PMAC/header
access, DMA tails, interface state, skb ownership and drop accounting are
validated by extracted sanitizer tests and compiled-MIPS bindings. MAC and
pause compatibility paths have focused regression coverage as well. Physical
receive, redirect and counter behavior remain hardware tests; see
``experimental/firmware-audit/ethernet-datapath-rx-audit.rst``.
The outer GSWIP receive path now also checks the callback result before
classifying a delivery as successful. Failed normal RX, redirected TX and LCT
deliveries increment the drop MIBs without retrying or freeing the
callback-owned skb. Seven extracted sanitizer cases, the rebuilt MIPS object,
the complete target suite and both image audits pass. Physical traffic and
counter validation remain outstanding; see
``experimental/firmware-audit/datapath-rx-accounting-audit.rst``.
Raw datapath RX/TX diagnostics now bound every ``skb->data`` dump by the
linear skb head and an optional print cap. This removes a zero-port path that
could select an oversized length and protects nonlinear traffic from raw
pointer over-reads. Eleven sanitizer cases, both rebuilt MIPS objects, the
complete target suite and both image audits pass; physical diagnostic-path
execution remains outstanding. See
``experimental/firmware-audit/datapath-debug-dump-audit.rst``.

Management-frame TX mappings now have explicit ownership and cleanup.
Pending management packets are now released before owner destruction, and
IRQ/tasklet draining precedes resource destruction. Unregister-phase callback
exclusion and recovery synchronization remain incomplete. See
``experimental/firmware-audit/wifi-teardown-audit.rst`` for the tested changes
and remaining source findings. Data-TX mapping ownership and rejected-send
cleanup are now corrected separately; see
``experimental/firmware-audit/data-tx-audit.rst``. These software fixes do not
establish working Ethernet/Wi-Fi or reliable installation on the device.
Recovery IRQ/tasklet draining and the order of event reopening are corrected
in ``experimental/firmware-audit/recovery-irq-audit.rst``. Data and public
management TX producers are now gated and drained, and reset initiation is
deferred and cancelled on removal; see
``experimental/firmware-audit/tx-gate-audit.rst``. The specifically audited
station VAP terminal-removal lifetime is now independently owned and deferred;
broader worker, callback and hardware lifecycle validation remains outstanding.
The platform also selects weak-memory ordering, matching the stock kernel;
SMP acquire/release operations must not silently become compiler-only barriers.
The subsequent ``experimental/firmware-audit/async-management-audit.rst``
corrects asynchronous station TX cookie/packet ownership, optional-callback
allocation failures and no-ACK packet completion. Patch 254 subsequently
closes the known station VIF/VAP removal paths; physical callback/workqueue
exclusion still requires validation.
Queued station TX requests now drain before recovery-context destruction and
mac80211 unregister; see
``experimental/firmware-audit/station-request-drain-audit.rst``. Pending firmware
completions, RX/status delivery and the broader recovery/removal lifecycle
remain unverified. The BSS confirmation path now reclaims a confirmed
descriptor after its VAP has been removed without resetting the card, and
retains the original frame's metadata while reusing a reserve slot. Native
and MIPS fixtures reproduce both old failures and pass with the fixes; see
``experimental/firmware-audit/bss-removed-vap-audit.rst``. Dynamic AP netdev
and VAP callback lifetime still require synchronization and hardware tests.

Source evidence
---------------

The exact vendor download page is:

https://www.tp-link.com/us/support/download/archer-ax3000/v1.60/

The page's listed V1.6 1.0.6 Build 20230831 download is byte-for-byte the
same 230831 ZIP used in the stock-firmware audit. See
``experimental/firmware-audit/v16-baseline-audit.rst`` for hashes and limits.

TP-Link links v1.6 to ``ax3000v1_GPL_3.tar.gz``:

https://static.tp-link.com/upload/gpl-code/2022/202211/20221107/ax3000v1_GPL_3.tar.gz

SHA256: ``de5befc72e4198e490ff4205439d4f8407175f92e487afc44071fd5a726be4c6``

Relevant paths within that archive:

* ``Iplatform/build/product_configs/ax3000v1/basic.config`` selects Intel
  UGW 7.5.1.50, GRX350, WAVE600, and Linux 3.10.104.
* ``Iplatform/build/product_configs/ax3000v1/kernel.config`` selects GRX500,
  big-endian MIPS32r2, and the 1 GiB EVA mapping.
* ``Iplatform/build/product_configs/ax3000v1/sdk.config`` specifies 256 MiB
  DDR, 128 MiB NAND, 115200 baud, and a 224 MiB memory setting. It also
  contains a later boot-argument override using all 256 MiB. This port
  exposes the lower 224 MiB: the actual stock SPL writes FMT1=0xfe002e00,
  mapping the bootcore's 32 MiB to physical 0x2e000000. Linux must exclude it.

The stock 1.0.6 firmware, build 20230831, has a valid legacy MIPS uImage
kernel header with load address ``0xa0020000``. Its embedded DTB describes
reference-board RAM and NAND sizes that conflict with the AX3000 product
configuration. Do not copy its partition definitions into a flashable image.

The platform startup and clock implementation are adapted from Intel's
GPL-2.0 submissions by Hua Ma, Yixin Zhu, and Songjun Wu:

* https://lists.openwall.net/linux-kernel/2018/08/03/90
* https://lists.openwall.net/linux-kernel/2018/08/03/91
* https://lists.openwall.net/linux-kernel/2018/08/03/92

Original copyright and license notices are retained in the adapted files.
Changes include current kernel APIs, appended DTB handling, SMP
startup, clock initialization and register-mask fixes, bounded peripheral
mapping, and the AX3000 device profile. This is not an upstream-endorsed port.

Build
-----

Select ``Intel GRX500 (experimental)`` and the TP-Link Archer AX3000 v1
device in ``make menuconfig``. Enable the initramfs image. A minimal seed is::

  CONFIG_TARGET_grx500=y
  CONFIG_TARGET_grx500_generic=y
  CONFIG_TARGET_grx500_generic_DEVICE_tplink_archer-ax3000-v1=y
  CONFIG_TARGET_ROOTFS_INITRAMFS=y
  CONFIG_TARGET_ROOTFS_SQUASHFS=y
  # CONFIG_KERNEL_WERROR is not set
  CONFIG_PACKAGE_kmod-iwlwav-stock=y
  CONFIG_PACKAGE_ax3000-stock-firmware=y
  CONFIG_PACKAGE_nand-utils=y
  CONFIG_PACKAGE_wifi-scripts=y
  CONFIG_PACKAGE_iw=y
  CONFIG_PACKAGE_wpad-mbedtls=y
  CONFIG_PACKAGE_wireless-regdb=y

Run ``make defconfig`` followed by ``make -j8``. Use OpenWrt's GCC toolchain;
LLVM's integrated MIPS assembler does not support all EVA assembly used by
this kernel. Images are under ``bin/targets/grx500/generic/``.

Build verification
------------------

The integrated kernel and userspace packages are built with Linux 6.18.55
and OpenWrt's GCC 14.4.0. Legacy vendor code still produces warnings; build
with CONFIG_KERNEL_WERROR disabled. The image audit in
``experimental/firmware-audit/verify-image.py`` binds the image to its ELF,
checks uImage CRCs and compression, and inspects its actual DTB and initramfs.
The resulting report records the artifact digest and every checked component.
For current wrapped images, supply ``--loader-elf`` from the corresponding
``*.relocated/loader.elf`` build directory. The audit binds the outer decoded
loader to that ELF, then binds the inner Linux bytes to the kernel ELF.

The exact stock firmware and GPL archive are pinned by SHA-256 in the firmware
and Wi-Fi packages. Source adaptations and direct Ghidra/REA findings are
retained under ``experimental/``. The earlier console-only image audit is a
historical baseline, not evidence about a subsequent networking image.

The unconnected-station Wi-Fi vendor request now retains its cfg80211 owner
until serialized measurement and event completion, and initializes every
error response before interface lookup. The exact Linux 6.18.55 wiphy/RTNL
contract, native sanitizer harness, MIPS module and current image artifacts
are bound in
``experimental/firmware-audit/unconnected-sta-lifetime-results.json``. This
is source/build evidence; the command's firmware latency and removal/recovery
behavior remain untested on the router.

The two asynchronous Wi-Fi channel producers now share a per-radio teardown
admission gate. Teardown closes it, cancels the control timers and drains any
producer already copying its raw master-netdev request before issuing the
existing synchronous serializer barrier. Native sanitizer and static-MIPS
race harnesses, all 28 driver scripts, the complete target suite and rebuilt
development images pass; exact bindings are in
``experimental/firmware-audit/async-channel-request-gate-results.json``. Real
DFS beacon/CAC overlap, firmware switching and unregister remain untested.

Patch 257 also replaces the fallible user-command removal barrier with a
stack-owned serializer command. It bypasses recovery readiness and ability
filters for local scan cleanup and drains a rejecting serializer before
unregister can proceed. Its failure reproduction, native/MIPS checks and
current image bindings are documented in
``experimental/firmware-audit/removal-scan-barrier-audit.rst``.

Patch 258 fixes serializer worker-creation failure handling: Linux error
pointers no longer pass the startup-success check or reach ``kthread_stop``.
The real vendor lifecycle macros are exercised with injected failures and
successful retries in native and MIPS fixtures; see
``experimental/firmware-audit/serializer-thread-start-audit.rst``. Actual
kernel allocation-failure and hardware startup tests remain outstanding.

Patch 259 also closes a use-after-free window in serializer diagnostics by
unpublishing the current command before its completion callback releases it.
The deterministic native/MIPS fixture checks concurrent enumeration after real
free, live-command visibility, queue ordering and early enumeration exit; see
``experimental/firmware-audit/serializer-current-lifetime-audit.rst``.

First hardware test
-------------------

Start with the initramfs image. It cannot be uploaded through TP-Link's
firmware-update page. It requires access to the U-Boot serial console and
a working RAM-loading method. The serial pinout, console access restrictions,
and bootloader command availability still need confirmation on v1.6.

Use a 3.3 V TTL UART adapter, common ground, and crossed TX/RX; do not connect
the adapter's power pin. The vendor configuration specifies 115200 baud;
start with 8 data bits, no parity, one stop bit, and no flow control. Capture
the stock boot log before interrupting autoboot. Do not guess the board pinout.

Inspect ``printenv update_chk run_bootcore`` first. Proceed only with a stable
stock bank state, ``update_chk=0`` or ``2``. States 1/3 are trial boots whose
stock initialization saves an environment transition. Preserve the stock
auxiliary-processor startup before downloading the RAM image, following the
vendor's own ``net_ram`` sequence. Once U-Boot has working Ethernet/TFTP::

  run run_bootcore
  setenv ipaddr <router-test-IP>
  setenv serverip <computer-TFTP-IP>
  tftpboot 0x80800000 <initramfs-kernel.bin>
  iminfo 0x80800000
  bootm 0x80800000

This template applies ONLY to current wrapped images with uImage load/entry
``0xa4000000``. Input at 8 MiB is decoded into the loader at 64 MiB, which
decodes Linux at 128 KiB. Do not load a wrapped image at ``0x84000000``:
that aliases its outer decompression destination. Confirm all used regions
are free using the actual bootloader's memory information before transfer.
The historical unwrapped images used a different RAM-loading address.
These commands are an untested template, not a verified installation method.
Do not use ``saveenv``, flash-update aliases, ``nand erase``, or ``nand write``.
The stock bootcore command attaches its existing UBI container; it is not a
zero-write NAND probe, and must run before the TFTP download.

RAM boot loads calibration and verifies existing UBI headers and volume-table
CRCs before attaching the stock container to read factory MAC data. The
factory JFFS2 volume is exposed and mounted read-only. UBI attachment itself
can update repair/wear-leveling metadata; this is not a zero-write NAND probe.
It does not install OpenWrt or replace the stock boot volumes.

The exact stock 1.0.6 upload checker has also been executed in isolated MIPS
emulation: it accepts the official firmware and rejects the raw OpenWrt
initramfs/sysupgrade image types, including the DirectConnect variant. An
experimental legacy factory container can be assembled for isolated tests,
but no hardware-validated stock-web image is approved for upload.
See ``experimental/firmware-audit/web-upgrade-audit.rst`` for the 12 checker
controls and 52 additional packaged MIPS userspace/serializer tests. Those tests
do not boot the kernel or establish hardware operation.

Without serial access, consult
``experimental/firmware-audit/serial-free-audit.rst``. Its laboratory legacy
container passes the stock checker and its kernel bytes pass a captured
writer-parser test. Starting the stock ubusd resolves the earlier emulated
thread teardown failure. No flash operation is performed and no factory
image is provided for upload. Wrapped kernel/rootfs pairs also pass capture
tests; this does not verify installation, boot or bank commitment.
The Ethernet-only installation and recovery path remains unfinished.

Capture the full boot log. At the OpenWrt shell, run ``ax3000-report`` to
collect read-only kernel, interrupt, link, radio and calibration diagnostics.
The image configures ``lan1`` through ``lan4`` in the LAN bridge and ``wan``
separately. Stock front-panel LAN numbering maps to physical ports 5,4,3,2.

Wi-Fi configuration is generated through normal OpenWrt detection and is
initially disabled. Set strong credentials, retain the US country setting,
and enable the detected 2.4 GHz and 5 GHz radios. Enable the interface
``wps_pushbutton`` option if WPS is desired on a compatible WPA2/mixed network. Test HE20/HE40 and HE80/HE160
where the regulatory database permits them. SAE requires PMF; test WPA2,
SAE and transition mode separately, including rejected replayed or malformed
management frames. The driver and host cryptography tests do not establish
the firmware's receive-side MIC/replay behavior.

Validate DHCP and bidirectional traffic on every LAN port, WAN routing and
isolation, then simultaneous dual-band association and traffic. Exercise
DFS/CAC, channel changes, recovery, USB2/USB3 storage, button actions and LED
state. Check calibration, PCIe interrupts and packet/error counters using
``ax3000-report``. Retain a stock boot log and factory partition backup before
attempting permanent installation.

Flash installation and upgrades
-------------------------------

The sysupgrade archive is for this OpenWrt target, not TP-Link's web updater.
Do not install the historical unwrapped images: their stock-address decoder
overlap is reproduced. Current wrapped images remain hardware experiments.
First establish a working RAM boot and recovery path on the actual unit.
The installation command from OpenWrt is::

  sysupgrade -n /tmp/openwrt-grx500-generic-tplink_archer-ax3000-v1-squashfs-sysupgrade.bin

The installer reads the CRC-checked redundant stock environment. Stable
``update_chk=0`` selects bank A and ``update_chk=2`` selects B; pending stock
trial states are rejected. The running rootfs bank must also match the saved
stable bank; a mismatch is rejected before any volume mutation. It requires the existing 124 MiB ``system_sw``
UBI container, bootcore and active kernel/rootfs volumes. It never formats
the container or writes bootloader, environments, calibration, bootcore or
the other stock bank.

New kernel, squashfs and an 8 MiB settings volume are staged in free space.
Preparation failures retain the active volumes. One UBI rename operation
switches all three names together and retains the previous contents under
``openwrt-backup-*`` names. The following upgrade may reclaim those backups.
The installer refuses insufficient free space instead of removing stock
volumes. Subsequent ``sysupgrade`` calls can preserve the normal OpenWrt
configuration archive. Fault-injection tests exercise this shell code, but
power-loss recovery and the stock bootloader handoff are still untested on
hardware.
