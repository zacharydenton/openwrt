GRX500 source experiments and evidence
=====================================

The active implementation is now integrated in ``../files``, ``../dts`` and
``../patches-6.18``, with stock firmware and WAVE driver packages under
``package/firmware/ax3000-stock-firmware`` and ``package/kernel/iwlwav-stock``.
See ``../README.rst`` for current build and testing instructions.

This directory retains the earlier Ethernet import/compilation recipe, the
abandoned newer-WAVE compatibility experiment, source manifests, stock
firmware analysis, and isolated PCIe/NAND validation. The older preparation
scripts reproduce their historical experiments; they are not the final
source of truth for the integrated target. In particular, the incomplete
newer WAVE patch is superseded by the exact-stock driver package.

The Ethernet sources originate from Intel Linux commit
``dc542d0ac6100123552c3a6ea12296061850e20b`` at
https://gitlab.com/prpl-foundation/intel/linux.git. The initial import and
Linux 6.18 compatibility patch are retained here. Subsequent changes in the
active overlay include DMA ownership and bounds checks, resource-based MMIO
addresses, deferred probe ordering, native PHY handling, bounded MDIO polling,
and error propagation. Retained copyright and license files identify the
vendor sources. The legacy code still has compiler warnings.

``firmware-audit/`` records REA package inspection and separately labelled
direct Ghidra decompilation, including exact firmware hashes and source
correspondence. ``pcie/`` and ``nand/`` record isolated compile/link tests and
source rationale. Their original test hashes describe those isolated builds;
the current image audit identifies the actual integrated artifact.

No result in this directory establishes hardware boot, association or packet
transfer. The first image is RAM-only; flash installation remains unimplemented.
