MAC event gate visibility across CPUs
====================================

The event-stop flags are written during removal and recovery while interrupt
and datapath handlers read them on other CPUs. The earlier source mixed plain
loads/stores with a few ``READ_ONCE`` and ``WRITE_ONCE`` accesses. Patch
``package/kernel/iwlwav-stock/patches/243-mac-event-gate-once.patch`` makes
all active accesses to both flags explicit. This prevents the compiler from
coalescing or inventing those gate accesses; it is not a substitute for the
separate tasklet, serializer and callback drains.

The patch applies cleanly after 242. Both MIPS package builds and complete
development/factory image builds pass. The prepared driver sources are
byte-identical in both checkouts and contain 15 ``READ_ONCE`` and six
``WRITE_ONCE`` gate accesses, with no remaining plain active access. Both
packaged ``mtlk.ko`` files have SHA-256
``d149883612b3ab6ba4e28202fe0de2613aa6d836e96e80610ea0a5a14efb2ae0``.
The development initramfs and both sysupgrade audits pass; 350 factory build
inputs match the development tree. The first-boot prerequisite audit passes.

The new **unapproved** laboratory factory container has SHA-256
``7c7e6e880eb6cb5fc4c0da6088bec407a4bbd13d21969b254d937bf331e19dec``.
Its exact bytes pass all 16 stock checker/writer capture cases. The isolated
stock LuCI upgrade route preserves the container and dispatches the checker
before the writer. Isolated stock ``uhttpd`` accepts the exact 9,039,514-byte
multipart request in both tested modes. The current development/factory
relocation-loader reports and REA bootloader results pass the bound
boot-argument layout check, including three negative controls.
``mac-event-gate-once-results.json`` records the input and report hashes.

The test harness intercepts flash commands. Neither Linux nor radio firmware
has run on the user's router. Actual boot, Ethernet, Wi-Fi, recovery, NAND
writes and stock-bank fallback remain unverified. This image is not approved
for a stock-web upload.
