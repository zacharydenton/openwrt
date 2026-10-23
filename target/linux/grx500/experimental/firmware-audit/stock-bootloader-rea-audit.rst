Stock bootloader handoff inspected through REA
=============================================

This is static evidence for the Archer AX3000(US) V1 230831 bootloader carried
by the official firmware update. It is not a dump of the user's v1.6 router.
The extracted ``stock-uboot.bin`` is 343580 bytes with SHA-256
``87fae41adc20ac4855d0716917cf4aaebec3c5688102360849fd43475a693f13``.

The ``/home/zach/code/rea`` checkout was fast-forwarded from GitHub main to
``9eb829aca34be36ff112826337996f6139f82eff``. A local, uncommitted,
read-only ``mips_be`` raw-binary adapter selects Ghidra 12.1.2 language
``MIPS:BE:32:default``. The raw base ``0xa0400000`` is caller-supplied from
the bootloader's linked addresses, not inferred by REA. The earlier REA ELF
ABI refusal for separate stock MIPS executables remains in force.
The exact local adapter diff is retained at
``/home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-mips-be.patch``
(SHA-256 ``0af77662161fa3e3e51c821aed8f422c834b73ccf833f2af1790977729beaa68``).
On 2026-10-23 the checkout was fast-forwarded again to GitHub main
``7f9a03d6ab37a63ac1be768e3eae8545187f7d21``. The same adapter diff
reapplied cleanly, REA rebuilt, and its raw-image and ``bootm`` outputs were
byte-identical to the retained results below. The refreshed layout check
passed all three negative controls; its report is
``/home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-20261023-bootargs-layout-results.json``
(SHA-256 ``2e55b53caf29be9d4e9f43195486a3a9828bf28ce7c4e328bd96cec817e563bf``).
The GitHub checkout then advanced to
``0407bbfbe65e8fa475e8bb0c78c30170e2c2f55e``. The adapter diff remained
byte-identical and applied without conflicts. REA rebuilt; its raw-image,
board-initialization, RAM-size and ``bootm`` outputs are each byte-identical
to the earlier retained Evidence. The bound boot-argument check again passed
all three negative controls. Its new report is
``/home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-0407-bootargs-layout-results.json``
(SHA-256 ``f1d0018fd24cd5a0e5e699e297a1b5751343ee5639320f688eeab13915c159ef``).
After the latest pull to ``c106cf20cbfcec8e1fcd953ad8e52bdfbf8c3f9c``,
REA rebuilt with the same local adapter diff. All four raw U-Boot outputs
remained byte-identical, and the bound boot-argument check again passed its
three negative controls against both current loader reports. The fresh report
is ``/home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-c106-bootargs-layout-results.json``
(SHA-256 ``519bc1d48bb0f7dae6a9687bf715f70d7c22cfedb573b333902a98574c7b0227``).
On 2026-10-23 REA fast-forwarded again to GitHub main
``630e6becdf3114ca57818c17b36700355ad9696e``. Its eight pre-existing
local edits did not overlap the upstream changes and remained intact.
The project rebuilt under Node 24.22.1. Fresh REA import, board-init,
RAM-size and ``bootm`` JSON outputs for the pinned stock U-Boot are each
byte-identical to the earlier retained Evidence. The compiled relocation
loaders from the OpenWrt ``bf46a5077e`` patch-253 builds passed the bound
instruction and negative-control checks. ``verify-stock-bootargs.py`` then
passed all three mutated-instruction controls using the fresh REA results and
both current loader reports. Its report is
``/home/zach/code/archer-ax3000-bringup/artifacts/upstream-sync-bf46a5077e-p253/stock-bootargs-layout.json``
(SHA-256 ``70ba2ee6b0c62b5c69d93c98cea1c95f9b3fdabc53a27c5e98366ab9802e7909``).

REA load-image Evidence
``ev_4ce015b96ea9a0293966d9c90bcc19e38b68fd1f27507b3ce9129084b711aa0f``
verified all 23 mapping checks: original and imported digests match, the
whole initialized file maps from ``0xa0400000`` in the default address space,
and the selected language and entry match. The retained result is
``/home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-latest-load-image.json``
(SHA-256 ``4bd0f65d26684f3725445732fb28e6418bb8becb64bba7015bcb078426e95d0b``).
As a negative control, the same CLI refused ``0xa0400001`` before provider
startup because a MIPS instruction entry must be four-byte aligned; the
original bootloader digest was unchanged.

REA function Evidence
``ev_5f175fe55b65b487128325c083f45b558c55e6e6f9cffb1210d54b8b3f47091e``
describes the 960-byte function at ``0xa04240f0``. References within it include
``bootargs``, ``memsize``, ``initrd_start``, ``flash_start``, and
``Starting kernel ...``. Its Ghidra pseudocode obtains an argument pointer
through ``*(uint *)(*in_k0 + 0xc)``, converts it to the uncached MIPS alias,
constructs argv and environment data there, then calls the kernel entry with
``(argc, argv, env, 0)``. The retained result is
``/home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-bootm-function.json``
(SHA-256 ``33955e78b69142ed55bb3e79bd681b4eba4ed5268f3f1c809d048bdc8f8d3b74``).

The official GPL U-Boot ``arch/mips/lib/board.c`` allocates ``bd`` and then
``bi_boot_params`` below the reserved U-Boot code and malloc arena near the
top of detected RAM. Matching the pointer path in the binary to
``gd->bd->bi_boot_params`` is an interpretation supported by that source,
not a runtime address observation.

The exact binary allows a stronger static placement check. REA Evidence
``ev_8feabe4860eabf58ec7b561bafb0fe259017e85b253350c8516e36e48e34eec0``
shows the called RAM-size function returns either 128 or 224 MiB. The
board-initialization path in REA Evidence
``ev_798033463a740d8a3d73f23becb0ae294189437654f43695408aab2397f5a052``
uses that size, a ``0x80000000`` SDRAM base, and its reserved-top offsets to
store ``bi_boot_params`` at the detected top minus ``0x4c0048`` bytes. The
later ``bootm`` path reads the same board-descriptor field. The resulting
uncached argument addresses are ``0xa7b3ffb8`` for 128 MiB and
``0xadb3ffb8`` for 224 MiB. Both are above the Linux output ending below
``0xa3000000`` and the compiled loader ending below ``0xa6000000``.

``verify-stock-bootargs.py`` pins 38 MIPS instruction words and four data
pointers in this bootloader, binds the REA import and three function results,
and compares both current compiled-loader handoff reports. Its three mutated
instruction controls are rejected. ``stock-bootargs-layout-results.json``
records the addresses and hashes. REA's board-init dossier reports a short
FunctionManager body despite decompiling the larger path, so the exact-byte
check is the decisive evidence for that path. The live RAM-size choice,
reserved-memory behavior, cache state, and Linux execution on this router
remain unobserved. REA does not emulate the bootloader, and this audit does
not establish that a stock-web upload is safe.

The reproducible REA commands use the local adapter::

  GHIDRA_INSTALL_DIR=/opt/ghidra node /home/zach/code/rea/scripts/rea.mjs inspect-native-load-image /home/zach/code/archer-ax3000-bringup/stock-uboot.bin --target-format raw-binary --architecture mips_be --entry-point 0xa0400000 --provider ghidra --json
  GHIDRA_INSTALL_DIR=/opt/ghidra node /home/zach/code/rea/scripts/rea.mjs function /home/zach/code/archer-ax3000-bringup/stock-uboot.bin 0xa0400a70 --target-format raw-binary --architecture mips_be --entry-point 0xa0400000 --provider ghidra --json
  GHIDRA_INSTALL_DIR=/opt/ghidra node /home/zach/code/rea/scripts/rea.mjs function /home/zach/code/archer-ax3000-bringup/stock-uboot.bin 0xa041c964 --target-format raw-binary --architecture mips_be --entry-point 0xa0400000 --provider ghidra --json
  GHIDRA_INSTALL_DIR=/opt/ghidra node /home/zach/code/rea/scripts/rea.mjs function /home/zach/code/archer-ax3000-bringup/stock-uboot.bin 0xa04240f0 --target-format raw-binary --architecture mips_be --entry-point 0xa0400000 --provider ghidra --json

With those JSON outputs retained, run the bound layout check from the OpenWrt
root::

  python3 target/linux/grx500/experimental/firmware-audit/verify-stock-bootargs.py \
    --bootloader /home/zach/code/archer-ax3000-bringup/stock-uboot.bin \
    --rea-load /home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-latest-load-image.json \
    --rea-board-init /home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-board-init-function.json \
    --rea-initdram /home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-initdram-function.json \
    --rea-bootm /home/zach/code/archer-ax3000-bringup/bootloader-audit/rea-bootm-function.json \
    --loader-report target/linux/grx500/experimental/firmware-audit/loader-handoff-development-results.json \
    --loader-report target/linux/grx500/experimental/firmware-audit/loader-handoff-factory-results.json \
    --negative-controls \
    --output target/linux/grx500/experimental/firmware-audit/stock-bootargs-layout-results.json
