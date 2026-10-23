Experimental stock-web first-boot transaction
===========================================

Status: the earlier factory candidate is WITHDRAWN. Its startup checks allowed
premature bank commitment without functioning Ethernet or Wi-Fi. Current source
requires explicit root acceptance during a timed trial after device testing.
That manual path is not yet qualified on the router.
See ``network-acceptance-audit.rst`` for the regression and current behavior.
The installation description and earlier candidate tests below document the historical
candidate, not a currently approved flow. No router has booted these images.
This extends the decoder and stock-parser work in ``one-shot-audit.rst``.

Installation behavior
---------------------

The factory container contains a rootfs component followed by the relocated
kernel. The stock writer selects the opposite bank. It does not update U-Boot,
bootcore, the vendor firmware volume or calibration. Stock U-Boot's researched
trial defaults save the old stable-bank decision before entering the new bank.

The factory rootfs runs ``79_grx500_trial`` before OpenWrt's mount_root hook.
It requires the exact board, a single running rootfs bank, a compatible saved
trial state, and thirteen boot-command defaults matching the actual stock
bootloader. A single trailing space is permitted because the shipped addmisc
default contains one absent from sdk.config. The check reads the actual saved
environment on boot; it does not substitute built-in defaults.

The helper verifies both environment partitions' offsets, sizes, NAND type,
erase/page geometry and write permissions. The attached system_sw container
must have the researched geometry and both kernel/rootfs/bootcore bank sets.
The mounted SquashFS root must resolve to the running bank's ubiblock device.
Existing rootfs_data or openwrt-trial-data volumes cause refusal. Nothing is
removed or reformatted to make space. With enough free eraseblocks, the helper
creates and initializes a fresh 8 MiB UBIFS overlay, records its ownership,
then renames it rootfs_data. Normal mount_root mounts it before calibration
and factory-MAC setup.
The preflight also keeps capacity for stock's 20 MiB ``data_vol`` when that
volume is absent; see ``stock-fallback-data-audit.rst``.

The late service waits up to 30 minutes for startup prerequisites and explicit
acceptance: the
expected persistent overlay and SquashFS bank, factory LAN MAC, four LAN ports
in br-lan, WAN outside that bridge, LAN carrier and network service, DHCP/SSH
processes, two readable wiphys, and both calibration files. It tests an overlay
write/read before commitment. These are startup prerequisites, not packet-flow,
RF association, WPA3/PMF, DFS, USB or performance acceptance tests.

Only after ``grx500-trialctl accept`` writes a bank- and boot-bound marker does
it set update_chk and active_bank in ONE fw_setenv batch and
read both back. The normal sysupgrade path independently rejects a running
bank that differs from the saved stable bank. That closes the previous path
which could overwrite the original stock fallback from an uncommitted trial.

If preparation fails, no bank commitment is attempted and the late service
requests a reboot. If readiness or manual acceptance never arrives, it
requests reboot at the timeout. ``grx500-trialctl reject`` requests immediate
fallback only while the saved boot decision is still untouched. Rejection and
the environment save use one lock in the worker's private tmpfs directory;
once a save has started, rejection refuses
to promise fallback and the command reports an uncertain boot decision. The
worker then leaves the current boot running instead of automatically rebooting
into an unknown bank, including when restarted during the same boot.
Failure to create the early environment-config
temporary file also records the failure marker so the late reboot worker starts;
the previous hook silently exited without starting that worker. If an
environment update fails or its readback disagrees, it is not retried. The
researched default boot logic should select
stock after an uncommitted trial, but this is not a tested recovery guarantee.
Early boot hangs, failed reboot, failed U-Boot environment saves and NAND
power-loss behavior remain hardware questions.

Deliberate limits
-----------------

An interrupted preparation may leave its new staging/overlay volume behind.
A later factory attempt refuses that volume instead of deleting potentially
valuable data. This implementation does not provide an automatic repair path
for that condition. The unchanged original bank remains the intended fallback.
The serial-free requirement is preserved; no UART interaction is part of the
proposed factory flow. Ethernet DHCP/SSH is available after successful startup;
LuCI has not been added to this build. The manual control command is available
only in the opt-in factory image; an ordinary image cannot create the marker.

Evidence
--------

* The thirteen contract variables match the extracted stock bootloader's
  defaults; ``boot-contract-results.json`` records its digest and values.
* Nine real packaged-MIPS fw_printenv/fw_setenv cases pass on disposable
  redundant environment files. They cover CRC failures, generation ordering,
  equal generations, 255-to-0 wrap, preservation of other variables and the
  previous valid copy. The regular-file backend uses the same incremental
  flag scheme as NAND. No NAND ioctl or power-loss test is claimed.
* Fifty scenarios per shell in ``tests/test-trial.py`` run the actual shell policy in bubblewrap with
  fixture files and mocked flash/network leaves. Native and packaged-MIPS
  shells execute the policy. The latest MIPS suite covers both bank directions,
  stable boots, the real trailing-space default, malformed command lines,
  incompatible boot commands, read-only environments, insufficient space,
  existing overlays, missing bootcore, failed volume operations, failed
  readiness, failed commitment/readback and incorrect environment geometry.
  Four preinit cases force temporary-file creation to fail and check that only
  an opted-in board trial marks failure and starts the late worker.
  ``tests/test-trial-worker.py`` exercises the real worker's 30-minute timeout,
  delayed acceptance, immediate failure and single-attempt environment policy
  under native and packaged-MIPS shells.
* ``tests/test-upgrade.py`` verifies rejection of trial/ambiguous running banks
  before UBI mutation, alongside the existing staged-upgrade fault tests.

Build and artifact checks
-------------------------

The ordinary target leaves both environment partitions read-only. A separate
factory build enables ``CONFIG_GRX500_FACTORY_TRIAL=y`` in the target's kernel
configuration and selects ``CONFIG_PACKAGE_grx500-factory-install=y``. The
package adds an explicit opt-in marker. Bootloader, GPHY, calibration and
reserved partitions remain read-only in the factory build.

After a full build, ``verify-factory-prerequisites.py`` runs the complete
sysupgrade ELF/rootfs audit, checks packaged first-boot files and service
enablement, and reads the seven compiled partition descriptors out of the
bound Linux ELF. This checks actual compiled write permissions rather than
trusting a source configuration flag. The relocation loader's original uImage
is retained to make subsequent decoder tests reproducible.

``build-factory-image.py`` requires that matching factory prerequisite audit,
the pinned stock firmware and the matching sysupgrade archive. It assembles
the experimental legacy container and a SHA256 manifest. The exact generated
container must then pass ``test-stock-factory-envelope.py --factory FILE
--factory-sysupgrade ARCHIVE``. This still intercepts all shell/flash commands;
it does not execute the authenticated HTTP handler or install anything.

The current opt-in factory variant was rebuilt on OpenWrt
``a25fb079b1463cd5d7d69c6d9a1c28d873291ebb`` after the early failure-marker
fix, stock DMA0/DMA3 integration and stock ``data_vol`` fallback capacity guard.
``factory-current-prerequisites.json``
binds its sysupgrade rootfs, relocated kernel, matching ELF, first-boot files,
and compiled NAND permissions; ``factory-current-trial-results.json`` binds
the native/MIPS policy tests to this source. Neither report supersedes the
historical candidate's test records. No stock-web container from the current
build has been approved or released.

An explicitly unapproved laboratory container built from this same sysupgrade
passed all 16 stock checker/writer cases, including exact kernel and rootfs
extraction with the stock writer's flash commands intercepted.
``factory-current-stock-writer-results.json`` binds the candidate and captured
component hashes. The stock HTTP server separately accepted the same
multipart bytes under isolated QEMU (``stock-uhttpd-ingress-audit.rst``), but
the router's authenticated upgrade request and NAND writes were not run.
``factory-source-parity-results.json`` checks 346 identical target, Ethernet,
Wi-Fi, package and relocation-loader build inputs against the port source.
Only the explicit factory kernel flag and install-marker package selection
differ between the checkouts.
The packaged upgrade policy also requires SHA-256 hashes for the exact kernel
and rootfs tar members before any later UBI upgrade; see
``upgrade-payload-integrity-audit.rst``.

The local factory build is retained in ``archer-ax3000-bringup/openwrt-factory``.
Copying the prepared build initially exposed stale absolute paths in its
pkg-config files, causing the host APK tool's endian wrapper to include a
second wrapper instead of the system header. Relocating those copied metadata
paths and rebuilding host APK resolved the build failure; no APK source change
was needed. A fresh checkout does not need that copied-tree repair.

Hardware acceptance is still outstanding: complete boot, real NAND writes and
bank transitions, persistent settings after reboot, LAN/WAN traffic/isolation,
both radios and the requested Wi-Fi capabilities, USB, LEDs/buttons and failure
recovery. Passing the software checks does not certify those behaviors.

The stock capture test also exposed a vendor string over-read when the kernel
label occupied all 32 uImage name bytes: its diagnostic appended the first
LZMA properties byte. The builder now uses a shorter, NUL-terminated label.
The earlier laboratory candidate is retained separately as superseded evidence.
