Single-upload installation audit
================================

Verdict: unfinished; no factory image is ready for upload. The original images
have a reproduced stock-address decompression failure. The current image
recipe includes a relocation loader that passes isolated decoder tests.
No router, NAND controller, Ethernet path or radio has been exercised.

Stock boot memory failure and implemented fix
--------------------------------------------

The actual stock bootloader's default ``loadaddr=0x80800000`` and
``flash_flash`` command load the UBI kernel at RAM offset 8 MiB. The original
OpenWrt kernel expands at ``0xa0020000`` (RAM offset 128 KiB). Cached and
uncached addresses alias the same memory. A host memory model compiled from
the official GPL archive's U-Boot LZMA decoder reproduces corruption for all
four original OpenWrt kernels: decoding fails after 8,388,608 output bytes.
The original stock kernel succeeds under the same model. All five decode
correctly when their source is at offset 64 MiB. These are decoder executions,
not execution of the bootloader binary or GRX500 emulation.

``build-relocated-kernel.py`` preserves the Linux image and appended DTB. It
embeds their LZMA stream in a freestanding MIPS decoder at ``0xa4000000`` and
wraps that loader in a normal LZMA uImage. Stock U-Boot can decode the outer
stream from 8 MiB to 64 MiB without overlap; the second stage decodes Linux
to its original address. The second stage uses a stack below 64 MiB, bounds
Linux output below 48 MiB and loader/workspace below 96 MiB, and forwards the
four boot arguments. It changes no NAND, environment or MMIO registers.

The current image Makefile applies this wrapper to initramfs and sysupgrade
kernels. Loader ELF/manifest intermediates remain beside the kernel build
outputs. Image auditors require the corresponding ``--loader-elf`` and bind
its bytes before using its payload symbols, then bind the inner kernel to
the Linux ELF. Hardware startup, uncached execution and handoff are untested.

``test-boot-memory.py`` records 22 passing scoped assertions:

* Ten original-image memory cases, including four EXPECTED failures at the
  stock load address. A passing test here records the known failure.
* Four wrapped images decoded by the vendor decoder to exact loader bytes.
* Four second-stage C decoder executions, compiled for MIPS and run under
  isolated QEMU, reproducing the exact Linux/DTB bytes.
* Four malformed/oversized inner-stream rejection cases.

The startup assembly, kernel and hardware are not executed by these tests.
Use ``boot-memory-results.json`` for hashes and case outcomes. The vendor
decoder is from ``u-boot-2010.06.tar.bz2`` within the pinned official GPL
archive, not an unversioned replacement decoder.

``loader-handoff-audit.rst`` additionally checks the compiled, image-bound
startup and Linux handoff instructions in the current development and opt-in
factory variants. It does not execute the assembly or establish cache state.
``stock-bootloader-rea-audit.rst`` traces the exact stock bootloader's
argument-pointer path through REA and checks both encoded RAM-size cases
against the compiled loader. It cannot determine the live RAM-size choice.

Both integrated image builds reproduce the four tested transport kernels
byte for byte, with unchanged root filesystems. All four integrated image
audits pass. ``test-kernel-transport.py`` adds 20 assertions covering the
original images' known incompatibility, exact inner-kernel binding, missing
or mismatched loader ELFs, and unexpected boot addresses.

Stock updater lifecycle and container tests
------------------------------------------

``test-stock-factory-envelope.py`` now records 22 passing scoped assertions.
It runs the exact stock checker/writer with an intercepted shell and no flash
devices. The earlier ``pthread_cancel failed!`` exit was caused by absent
ubusd: launching the exact stock service in the private namespace makes the
writer exit zero. Four no-ubus cases retain the expected failure as controls.

Both wrapped initramfs candidates and both wrapped kernel/rootfs pairs pass
the stock checker. The writer emits the exact expected kernel and rootfs
bytes. Rootfs is a type-7 uImage preceding the kernel; the writer removes its
header. Kernel is type 2 and retains its header. Captured commands never run.
The harness deletes prospective containers and emits no upload image.

The writer can return zero even after rejecting a damaged component CRC.
Therefore tests assert diagnostic output and captured component identities,
not just process status. Likewise child flash, cleanup and reboot commands
are intercepted; zero status does not establish a successful installation.

Bank switching and unresolved installation requirements
-------------------------------------------------------

``test-stock-bank-switch.py`` executes the actual extracted
``upgrade_dualvol_kernel`` shell body with mocked leaf operations. Ten cases
cover both banks, failed kernel writes and each failed environment update.
A failed kernel write prevents environment changes. The three environment
writes are separate, and failure of the first or second does not stop later
updates. This is source control-flow fault injection, not NAND fault injection.

The default U-Boot trial logic resets the saved state to the old stable bank
before booting the new bank; stock ``ltqboot`` later commits its own startup.
``stock-boot-fallback-audit.rst`` binds the ``save`` abbreviation and both
two-boot transitions to the pinned U-Boot command table, GPL parser and stock
``ltqboot`` script. It also records the saved ``active_bank`` mismatch after a
fallback selection. These are static/model checks, not physical rollback.
The opt-in factory variant now implements a first-boot transaction; see
``factory-trial-audit.rst``. The normal sysupgrade installer also rejects a
mismatch between running and saved banks, preventing it from overwriting the
stock fallback during a trial. Mocked policy tests pass in native and MIPS
shells; no physical environment or volume write has been verified.

Still unverified on a physical router: authenticated HTTP upgrade execution,
actual UBI capacity and bad blocks, overlay initialization, durable bank/environment transitions,
bootcore compatibility, hardware startup and reliable recovery from failed
startup. The unverified default trial logic is not a recovery guarantee.
The user's serial-free constraint remains the installation requirement.

Reproduction
------------

Build each transport with ``build-relocated-kernel.py --openwrt ROOT --kernel
ORIGINAL_UIMAGE --output NEW_DIRECTORY``. Then run ``test-boot-memory.py`` with
``--openwrt``, ``--bringup``, ``--uboot-src``, ``--relocated`` and ``--output``.
The relocated directory contains ``relocated-{software,directconnect}-
{initramfs,sysupgrade}`` builds. Add ``--relocated`` to the existing stock
factory-envelope test arguments to include these candidates. Run the bank
test with ``--vol-mgmt STOCK_ROOT/usr/sbin/vol_mgmt --output REPORT``. Full traces, manifests and
build logs are retained under the bringup ``one-shot-audit`` directory.
