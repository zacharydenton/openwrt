AX3000 US V1 stock firmware versus the OpenWrt experiment
=======================================================

The initial console-only OpenWrt image failed 13 networking prerequisite
checks. That result is retained as ``console-image-audit.json``. It prompted
the integrated Ethernet, PCIe, NAND and stock WAVE600 implementation now in
the GRX500 target. ``current-image-audit.json`` is regenerated against each
final RAM image; its image digest identifies the artifact actually checked.

The later ``one-shot-audit.rst`` records a reproduced stock-address boot-memory
failure in the original images, the relocation loader now used by the build,
and the remaining single-upload installation work. The current image audits
cover both outer loader and inner Linux ELF bindings. No factory upload image
is ready, and checker/decoder success does not prove hardware startup.

The stock firmware investigation resolves board wiring, initialization and
calibration details. Static comparison cannot establish that the new kernel
boots, that DMA works, or that either radio transmits correctly. No hardware
execution or flash write has occurred during development.

Upstream synchronization on 2026-10-23
------------------------------------

The development, factory and DirectConnect checkouts were fast-forwarded to
OpenWrt ``bf763871e9``. The only incoming change disables ``RAVE_SP_CORE`` in
the generic Linux 6.18 config. All three images rebuilt and passed their
image/ELF/rootfs audits. The replacement factory container passed 16/16 pinned
stock checker/writer cases and the isolated stock Lua upload-route check;
``upstream-sync-bf763871e9-results.json`` binds the exact digests. The
container remains **unapproved for upload**. These checks do not exercise the
router, and recovery/VAP deletion overlap remains under audit.

Patch 250 subsequently added a recovery/VAP lifetime gate. Its rebuilt
development, factory and DirectConnect images, native/MIPS interleaving tests
and replacement stock-container checks are recorded in
``recovery-vap-lifetime-fix-results.json``. The older container above is
superseded. The patch closes the modeled overlap; physical recovery and
station-removal failure handling were still unverified in that artifact.
Patch 254 later closes the known station source paths. Fresh development
initramfs and sysupgrade images build and pass their static audits, but no
replacement factory container was built; every retained container is still
**unapproved for upload**.

Evidence examined
-----------------

The input is TP-Link's Archer AX3000(US) V1 230831 update:

https://static.tp-link.com/upload/firmware/2023/202309/20230906/Archer%20AX3000%28US%29_V1_230831.zip

ZIP SHA-256:
``6198caa78034f69a029b1e4009c2a69f4c36ea9e673e75338b50925543198846``.
Firmware payload SHA-256:
``96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b``.
This is a V1-family update, not a dump of the user's particular v1.6 router.
``v16-baseline-audit.rst`` verifies that TP-Link's US V1.60 support page
offers this exact same 230831 ZIP for its listed 1.0.6 build.

REA 6.7.0 was initially built from the requested ``/home/zach/code/rea`` checkout at
``d0067ba34a39ea47dd7e11bb2e6169bc0938cc3f``. Its archive inspection verified
the ZIP members and produced Evidence
``ev_74bf2b2e47c984f15870f141ab76ddfe4f41b59436fa0899d3520bbbae87a319``.
REA refused the stock MIPS executable analysis because these explicit-o32 ELFs
lack the ABI flags records required by its adapter. That limitation was not
bypassed for those ELFs. Direct Ghidra 12.1.2 then decompiled the utilities and
selected Wi-Fi driver functions. Those results remain labelled direct Ghidra
output, not REA Evidence. The REA checkout was later fast-forwarded to GitHub
main ``9eb829aca`` and locally extended for raw big-endian MIPS bootloaders.
``stock-bootloader-rea-audit.rst`` records the new REA Evidence and limits.
The GitHub checkout was later updated to ``7f9a03d6a``; the raw bootloader
mapping and ``bootm`` function Evidence reproduced byte-for-byte.
Its bound exact-binary check places U-Boot's boot arguments above the compiled
loader and Linux output for both RAM sizes encoded in this stock bootloader.

``evidence-index.json`` records the retained outputs and their digests.
``stock-image-manifest.json`` records seven outer/nested uImages plus the
decompressed GPHY uImage; all eight header/data CRC pairs passed. It also
records kernel, DTB, rootfs, bootloader and raw GPHY extraction hashes. CRC
validation establishes integrity, not a cryptographic signature check.

Findings that change the port
----------------------------

* LAN1, LAN2, LAN3 and LAN4 map to GSW-L/MDIO ports 5, 4, 3 and 2.
  WAN uses GSW-R datapath port 15 and MDIO address 1. The stock switch startup
  initializes VLANs and duplex before enabling ports.
* Stock Ethernet uses ``lantiq,xrx500-net``; the imported driver matches
  ``lantiq,xrx500-eth``. A verbatim stock DT node would not bind it.
* Stock PCIe2 uses GPIO bank 0 line 14, active-high. Generic reference GPIO
  line 7 was not correct for this firmware. PCIe0 and PCIe1 use bank 1 lines
  11 and 29, active-low, with a separately encoded reset polarity.
* Legacy GIC numbers include an offset of eight. PCIe MMIO addresses require
  parent-bus translation. CBM sends stock CPU traffic through dequeue port 2;
  this must be adapted deliberately for the SMP kernel and its shared hardware queue locks.
* The shipped Wi-Fi module identifies version/revision
  ``6.0.8.0.87.0.7 / d24084bd3447``. The TP-Link GPL archive contains a source
  package with those identifiers. Selected decompiled firmware-loading paths
  agree with that source. Its archive SHA-256 is
  ``c9dcd2b8a97d5cbc303303891daffbedb43acd918971175d980eca9e85212be4``.
* Radio firmware filenames are selected from the detected chip revision.
  Stock carries the Gen6 A0 AP image; this and the matching loader support an
  A0-oriented configuration inference. The actual chip register has not been
  read. The newer experimental driver omits A0 dispatch, so it is not a
  justified replacement for this stock path.
* Calibration is a nested archive: ``calibration`` MTD contains
  ``wlanconfig.gz``, which contains ``cal_wlan0.bin`` and ``cal_wlan2.bin``.
  Firmware-loading requests must receive these per-device files before radio
  initialization. ``cal_cbr`` is backup/recovery code with a flash-write path;
  it must not be copied into a read-only collection or extraction workflow.
* The bootloader binary contains both a 224M default and an ``addmisc`` command
  appending ``mem=256M@512M``. The DTB retains a 480 MiB reference map. These
  values do not establish runtime reservations or a safe flash layout.

``board-notes.rst`` and ``stock-board.json`` retain addresses, phandle
resolution, queue tables, source locations and GPIO/IRQ interpretation.
``binary-findings.rst`` gives function addresses, decompiler provenance,
firmware naming, calibration recovery and remaining unknowns.

Reproduction
------------

From the OpenWrt repository root, extract the inspected firmware to a **new**
working directory outside this source tree::

  python3 target/linux/grx500/experimental/firmware-audit/extract-stock.py \
    /path/to/stock-230831.bin /path/to/new-extraction

This version-pinned extractor validates the images before writing outputs.
The raw GPHY payload is 65,536 bytes. The ax3000-stock-firmware package now installs it for the GPHY loader. Extract ``rootfs.squashfs`` with
the built OpenWrt ``staging_dir/host/bin/unsquashfs4`` if needed. The board
decoder invocation is documented in ``board-notes.rst``; the direct Ghidra
invocation is in ``DecompileStock.java``.

Audit the built RAM image and the corresponding ELF::

  python3 target/linux/grx500/experimental/firmware-audit/verify-image.py \
    --image bin/targets/grx500/generic/openwrt-grx500-generic-tplink_archer-ax3000-v1-initramfs-kernel.bin \
    --elf build_dir/target-mips_24kc_musl/linux-grx500_generic/vmlinux-initramfs.debug \
    --cross-compile "$PWD/staging_dir/toolchain-mips_24kc_gcc-14.4.0_musl/bin/mips-openwrt-linux-musl-" \
    --output /path/to/current-image-audit.json

The original console image returned status **1**, with 13 missing
prerequisites. Status 2 means malformed or unverifiable input. Status
0 establishes only presence of the checked ingredients, not functioning
hardware. The check covers the chosen vendor baseline's built-in driver names;
modular replacements or different implementations need explicit audit updates.

The audit reproduces kernel bytes from the supplied ELF using OpenWrt's
objcopy recipe, compares them with the decompressed image, and reads the DTB
and initramfs from those verified bytes. It cannot accidentally credit the
separate networking ELF to the console image. ``console-image-audit.json``
records that original run. A corrupted image payload and that unrelated networking ELF
were both tested and rejected. Fresh stock extraction matched the previously
examined kernel, DTB and rootfs byte-for-byte. The DT parser was checked against
dtc roundtrips for all 195 stock and 12 OpenWrt nodes.

Integrated implementation and hardware boundary
-----------------------------------------------

The target now includes Ethernet DT bindings, reset/GPHY setup, CBM CPU
routing, DMA ownership changes and board network configuration. PCIe
host/PHY/reset/GPIO support, BCH NAND and protected factory partitions are integrated.
``package/kernel/iwlwav-stock`` ports the exact stock A0-capable source to
native Linux 6.18; ``package/firmware/ax3000-stock-firmware`` supplies its
matching generic radio firmware. Preinit retrieves the device's own
calibration before module autoload. Neither archive substitutes calibration
from another router.

The integrated image still needs an observed boot, each LAN/WAN port, routing and
isolation, and simultaneous 2.4/5 GHz association and traffic tests on v1.6.
The native driver now translates HE capabilities, supports contiguous 160 MHz,
and implements SAE/PMF integration. USB, LEDs/buttons and atomic UBI upgrade
code are included. These runtime checks cannot be replaced by a checksum or
compiler; see the target README and package test reports for their boundaries.

``scan-cancel-audit.rst`` records the Linux 6.18 scan-cancellation callback,
removal-time scan drain and modeled native/MIPS tests. It does not establish
runtime scan behavior or safe stock-web installation.
``vht160-band-audit.rst`` binds the 5 GHz-only VHT 160 MHz guard to the
compiled MIPS module and both rebuilt image payloads; RF use remains untested.
``control-timer-audit.rst`` records the scheduled-scan self-cancel fix and
removal-time CAC/scheduled timer drain, including the limits of its modeled
tests.
``bss-removed-vap-audit.rst`` records the late BSS-confirmation and reserve
metadata fixes, native/MIPS handler tests, and the remaining AP lifetime risk.
``vap-rtnl-lifetime-audit.rst`` traces the unresolved cross-thread RTNL and
published-VAP cleanup defects in the dynamic AP interface path.
``dfs-workqueue-quiesce-audit.rst`` records the DFS callback drain before
Wi-Fi unregister, native/MIPS race fixtures, and exact rebuilt-image bindings.
``mac-callback-quiesce-audit.rst`` records the station RX/status drain before
unregister and the current unapproved image bindings.
``ap-status-gate-audit.rst`` records the AP management-status exception fixed
in the reserved-BSS failure path and the latest unapproved image bindings.
``network-board-audit.rst`` records the rebuilt DTB's stock-derived network
wiring comparison, including DMA0 and DMA3/TOE clock bindings and their
runtime limits.
``factory-current-prerequisites.json`` and ``factory-current-trial-results.json``
bind the rebuilt opt-in factory variant's packaged first-boot files, compiled
NAND permissions, and native/MIPS fallback-policy tests. The current source
cannot commit automatically: an explicit root command after device testing is
required, and that path remains unqualified on hardware.
``factory-current-stock-writer-results.json`` binds the same build's unapproved
laboratory container to the stock checker and intercepted writer results.
``stock-web-route-audit.rst`` runs the stock MIPS Lua multipart parser,
upload handler and checker/writer dispatch on that exact container with all
external commands intercepted. ``stock-uhttpd-ingress-audit.rst`` runs the
stock MIPS HTTP server and ubus daemon against the same multipart body; the
server accepted it in two HTTP modes and delivered identical bytes to a
disposable CGI. The authenticated LuCI route was not exercised over HTTP, and
physical installation remains untested.
``stock-boot-fallback-audit.rst`` binds the stock U-Boot ``save`` abbreviation
and both trial-to-previous-bank transitions to the exact binary and GPL source.
It does not prove a physical reset or successful stock fallback.
``manual-acceptance-audit.rst`` describes the explicit root command, the
30-minute uncommitted trial and its native/MIPS policy tests.
``factory-source-parity-results.json`` checks the factory checkout's build
inputs against the port source, including Ethernet, Wi-Fi and the relocation
loader.
``upgrade-payload-integrity-audit.rst`` records the per-payload sysupgrade
checksums and the native/MIPS corruption-rejection tests for both current
image variants.
``upgrade-env-geometry-audit.rst`` records the stock boot-environment partition
geometry gate and its native/MIPS upgrade tests. A mismatched layout is
rejected before the environment is read or UBI is touched.
``stock-fallback-data-audit.rst`` checks that the trial leaves capacity for
stock's ``data_vol`` if a failed trial returns to the old bank.
``loader-handoff-audit.rst`` records instruction-level checks of the compiled
relocation loaders in both current image variants, with the physical cache and
kernel-boot limits stated separately.
``upstream-sync-bf46a5077e-results.json`` records the latest upstream pull,
three successful builds and their static image checks. The factory and
development trees retain 360 matching runtime build inputs.
``station-remove-terminal-audit.rst`` and
``station-vif-reader-lifetime-results.json`` record the original two terminal
station-removal failures, patch 253's removal of an unused tasklet VIF reader,
and patch 254's independent deferred VAP/netdev ownership repair. The native
sanitizer cases and complete 26-script host suite pass, the MIPS package links,
and fresh development initramfs and sysupgrade images pass their static
audits. No factory container contains patch 254; the existing laboratory
container must not be uploaded through the stock web interface.
``unconnected-sta-lifetime-audit.rst`` records patch 255's correction of a
raw ``wireless_dev`` pointer queued beyond its nl80211 callback and an
uninitialized result on the first stale-interface error. The exact target
kernel's vendor-command wiphy/RTNL contract, extracted ASan/UBSan submit
cases, all 27 driver scripts, MIPS package and current images pass; real
measurement, recovery/removal overlap and RF behavior remain untested.
``async-channel-request-gate-audit.rst`` records patch 256's correction of
the two asynchronous ``SET_CHAN`` producers that could copy a raw master
netdev across Wi-Fi teardown. Native sanitizer and static-MIPS race cases, all
28 driver scripts, all 15 target scripts, clean package/target/full builds,
both image audits and packaged-MIPS corruption checks pass. Real DFS/CAC,
firmware, unregister, RF, boot, flash and fallback execution remain untested.
``removal-scan-barrier-audit.rst`` records patch 257 and five reproduced failures
of the old removal barrier. The replacement uses a stack-owned serializer
command and drains a rejecting serializer before local scan cleanup. It closes
the failure-handling gap left by patch 256's admission gate; native/MIPS
fixtures cover FIFO order, cancellation, rejection and repeated stop.
``serializer-thread-start-audit.rst`` records patch 258's correction of the
worker-creation result check. Actual vendor lifecycle macros previously
accepted every tested Linux error pointer; the corrected code rejects all
4,095 encodings and permits successful retries without stopping an invalid
task. Native sanitizer and static-MIPS fixtures model the kthread/event leaves.
``serializer-current-lifetime-audit.rst`` records patch 259's correction of a
current-command pointer left published across freeing completion callbacks.
A controlled concurrent reader observes freed commands before the patch and
none after it, using extracted enqueue/worker/enumeration/completion functions
with pthread synchronization and real allocation/free.
``ethtool-autoneg-audit.rst`` records the correction of the GRX500 Ethernet
autonegotiation-restart callback, which previously returned success without
touching the PHY. The extracted sanitizer test, MIPS kernel object, full
development build and current image audits pass; physical renegotiation on
all five ports remains untested.
``ethernet-flow-control-audit.rst`` records the correction of the registered
datapath stop/restart callbacks and empty netdev timeout handler. Extracted
sanitizer cases, the linked MIPS kernel, complete native suite, full image
build, static audits and packaged-MIPS payload corruption checks pass. Actual
CBM/TMU congestion, watchdog recovery and interface-shutdown races remain
untested on the router.
``ethernet-datapath-rx-audit.rst`` records the callback's missing datapath
TX mode and its length, header, tail, interface-state, ownership and drop
accounting repairs. It binds the two-mode API to official UGW 8.5.2 source,
extracted ASan/UBSan tests, the linked MIPS object and the current audited
images. Physical LAN/WAN receive and redirect traffic remains untested.
``datapath-rx-accounting-audit.rst`` records the adjacent outer-datapath MIB
repair. Callback failures now select the per-subinterface/global drop counters
instead of RX, redirected-TX or LCT-clone success counters, without violating
the callback's consumed-skb ownership. Seven extracted sanitizer cases, all
15 zero-argument GRX500 scripts, the linked MIPS object, both rebuilt image
audits and packaged-MIPS corruption controls pass. Physical packet and counter
behavior remains untested.
``datapath-debug-dump-audit.rst`` records the RX/TX raw diagnostic-dump
repair. All skb-backed raw dumps now stop at the linear head, respect offsets
and apply a positive print cap; the zero-port error path no longer chooses the
larger, unsafe length. Eleven extracted sanitizer cases, all 15 zero-argument
GRX500 scripts, both linked MIPS objects, both rebuilt image audits and
packaged-MIPS corruption controls pass. Physical diagnostic-path execution
remains untested.
