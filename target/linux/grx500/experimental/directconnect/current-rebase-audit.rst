DirectConnect variant rebased on the current AX3000 port
======================================================

The opt-in variant was rebuilt in an isolated checkout of OpenWrt
``d014acb494001606ce78720e240892e840302a9d`` with the current AX3000
port and Wi-Fi patches 243–245. Patches 244 and 245 have SHA-256
``6d17acbac28e1a4fb197ac8820f4021e5be9797ae9804ad68603213957c3f9c8`` and
``2079a25d805f36ae309f4df2c2a819ce8086354cb55be89f63641d3892362f9e``.
The variant applier completed after the current port was copied into that
checkout. ``make defconfig`` selected ``kmod-directconnect-grx500`` and
``kmod-iwlwav-stock``; a clean Wi-Fi package build and complete ``make -j8 V=s``
passed. A second complete build passed after the upstream update. The prepared driver has 15 ``READ_ONCE`` and six ``WRITE_ONCE`` MAC
event-gate accesses. Its prepared ``hw_mmb.c`` is byte-identical to the
ordinary build, SHA-256
``8f2d4ffd78d6d2c4a4d8b338e56d4849e72d7989ba7137774b5fe88a3aaa4b04``.
The DirectConnect package's stripped ``mtlk.ko`` SHA-256 is
``1b2563bc7eb198b936e0c98855442c63c0a84d7d39291752cef99d62566d2177``.

The source export test passes against the normal port's current prepared
kernel and Wi-Fi sources, using the pinned DirectConnect archive. The UMT
MMIO/counter host harness also passes. The image audits bind the generated
images to their compiled kernel ELF files and find the UMT DT node, required
kernel exports, both DirectConnect modules and ``fastpath=0,0,0`` autoload:

* RAM initramfs SHA-256:
  ``6a98b3d3cac20b572ce1f20bba9a2ad6dbf604d6a73ec342eaae11f4fee0adcc``.
* Sysupgrade SHA-256:
  ``6104a45459d061f2fec9fb22f9924fbcb20733d045e64bf1b84a76828b05759e``.
* RAM image audit SHA-256:
  ``2823e88fe9fd431a3cce20a971ba015fd20ccb8eca1801b57527d008db7f4d48``.
* Sysupgrade audit SHA-256:
  ``e469dd29bad7cf143f9a935805177f95423545f3bb914ff62c6327e227fe6e9b``.

Both relocation-loader handoff checks pass with negative controls. The
REA-bound check of exact stock U-Boot instructions and both compiled loaders
passes for the boot-argument layout, also with negative controls. Reports
are retained under ``/home/zach/code/archer-ax3000-bringup/bss-removed-vap-audit/``
as ``directconnect-d014ac-{ram,sysupgrade}-loader.json`` and
``rea-d014ac-bootargs-layout.json``. The actual full BSS completion handler also
passes the native and MIPS fixtures described in
``../firmware-audit/bss-removed-vap-audit.rst``.

This is compile, image, and host-harness evidence. Neither the optional
variant nor the normal port has booted on the user's router. UMT IRQ/DMA
progress, Ethernet and Wi-Fi traffic, VLAN/isolation, recovery and flash
installation remain unverified. The variant is not a PPA/MPE port and does
not establish stock throughput. No DirectConnect factory upload is approved;
the normal image continues to use the software datapath.
