Compiled relocation-loader handoff audit
=======================================

The development and opt-in factory sysupgrade images use a second-stage MIPS
loader at 0xa4000000. ``verify-loader-handoff.py`` takes each image's existing
ELF-binding report and rejects a different loader ELF. It then checks the
compiled ELF entry, absence of unresolved relocations, memory regions and
machine instructions rather than relying only on ``relocated-kernel.S`` and
``relocated-kernel.c`` source text.

Both bound loaders pass. The first eleven instructions save U-Boot's stack and
return address, enter a separate stack below the loader, and restore both on
decoder failure. The compiled C path saves all four MIPS o32 boot arguments,
calls the decoder with output at 0xa0020000 and the 0x02fe0000-byte limit,
orders writes with ``sync``, restores all four arguments, and branches to the
Linux entry. The kernel output remains below 0xa3000000, the loader stack is
at 0xa3ff0000, and the loader including BSS ends below 0xa6000000. Two
mutated-instruction controls are rejected in each build. The exact addresses,
loader hashes, image-report hashes and controls are in
``loader-handoff-development-results.json`` and
``loader-handoff-factory-results.json``.

The loader's probability array is in an ELF ``NOBITS`` section, absent from
the binary expanded by U-Boot. The matched ``LzmaDecode.c`` initializes all
probabilities selected by the validated lc/lp properties before decoding, so
this one array does not require U-Boot to clear BSS. The GPL U-Boot
``arch/mips/lib/board.c`` allocates its Linux argument block near the reserved
top of RAM, which is distinct from the lower 48 MiB Linux output in that
source flow. This is source evidence, not a readout of the user's bootloader.

The checks do not execute MIPS startup, model the actual GRX350 caches, or
prove that Linux begins running. In particular, the second stage writes the
kernel through an uncached alias and issues ``sync`` before jumping; physical
cache state and the later cached kernel path still require hardware evidence.
REA's separate ``stock-bootloader-rea-audit.rst`` derives the shipped
bootloader's argument addresses for both encoded RAM-size choices. It does
not observe the user's live RAM-size choice or prove a physical boot.
This audit strengthens the static handoff check but does not make a stock-web
factory upload safe.
