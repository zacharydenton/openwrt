Optional GRX500 DirectConnect transport
======================================

This directory contains an opt-in OpenWrt package/kernel variant. The normal
AX3000 image continues to use the software Wi-Fi datapath. Even after applying
this variant, ``mtlk`` retains ``fastpath=0,0,0`` by default. All four Linux CPUs
remain available. This is a DirectConnect ring/UMT transport port, not a PPA or
MPE acceleration implementation; no throughput or hardware acceptance is claimed.

Apply to an alternate checkout containing the current AX3000 port::

  python3 target/linux/grx500/experimental/directconnect/apply.py /path/to/alternate-openwrt
  cd /path/to/alternate-openwrt
  make defconfig
  make -j8 V=s

The applier installs package/kernel/directconnect-grx500, adds it as an iwlwav
build/runtime dependency, enables CONFIG_GRX500_UMT, copies the kernel/helper and
Wi-Fi patches, and includes the exact stock-address UMT DT node. It does not alter
CPU count, enable MPE/PPA, or change the fastpath module parameter. The package
installs its real exported symbol table and API header for the Wi-Fi build.
The normal kernel/image build produces the alternative image; no separately
constructed factory header is supplied here. Keep the ordinary image separately.

For the hardware experiment, activate the alternative driver/kernel combination
by changing only ``fastpath=0,0,0`` to ``fastpath=1,1,0`` in
``/etc/modules.d/60-iwlwav-stock`` and rebooting. Preserve the other module
parameters. Read ``/sys/module/mtlk/parameters/fastpath`` after boot and check the
kernel log for the negotiated DC mode and UMT/DMA initialization. To return to
the software path, restore ``fastpath=0,0,0`` in that file and reboot. The optional modules require the UMT and
CBM/HDMA/bridge helper exports from the alternative kernel. They cannot be loaded
into the normal kernel. Software fallback is selected with ``fastpath=0,0,0``.
Do not enable the stock software DC modes or PPA/MPE components: they are outside
this transport variant. Optional station-only PHY support continues to use the
software datapath; the DirectConnect netdev identity check accepts native AP
interfaces, including OpenWrt's phy*-ap* names.

Changes and policy
------------------

* Native UMT reproduces the stock expanded register layout, DMA1TX channels 7–10,
  MSG0 hardware counter and software MSG1 dequeue-counter workaround. A Linux
  hrtimer replaces the vendor GPTC/MIPS yield-thread scheduler. It uses the stock
  40us tick and 32-entry notification cap, checks reset completion, and serializes
  configuration/release against timer MMIO writes. It does not reserve a VPE.
* CBM supplies real platform-resource physical addresses for peripheral rings.
  HDMA supplies the actual DMA device. RX pools use coherent DMA allocations;
  fragment repair resolves DMA handles only within those pools, validates
  bounds and ownership, and publishes descriptors with DMA barriers.
* Wi-Fi private skb state starts after the 16-byte datapath descriptor area.
  A compile-time size check prevents overlap. TX explicitly initializes those
  descriptor words before handing ownership to DirectConnect.
* GSW-R peripheral ingress explicitly selects CPU port 0. The stock setting that
  enables direct same-port VAP forwarding is omitted. No PPA bridge/session hooks
  are enabled. Linux bridge VLAN, STP and AP-isolation decisions therefore remain
  on the software path; this intent still requires packet-level hardware tests.
* Bridge teardown removes only dynamic entries on the requested interface;
  static/local entries and entries on other interfaces remain intact. MACDB
  notifications distinguish VLAN IDs and hold netdev references through RCU.
* Unsupported checksum/SG promises are removed. RX defaults to CHECKSUM_NONE
  because this transport has no validated per-packet checksum-status contract.
  Registration failures release rings and do not release another shared port's UMT.

Reproducibility and evidence
----------------------------

``provenance.json`` records the exact stock WAVE archive hash, stock DTB hash,
DirectConnect source commit/archive hash and kernel baselines. DirectConnect is
Intel's published UGW 8.5.2.10 source, commit
6ceb742215486e690c6c8604f06a81415d12f398, API 0x050007. It is not represented as the
exact original AX3000 DirectConnect module source. The stock AX3000 build enables
LTQ_HWMCPY, LTQ_UMT_EXPAND_MODE and LTQ_UMT_SW_MODE; its stock modules import the
UMT/CBM/HDMA interfaces. Native UMT register definitions, counter-delta/cap logic,
reset and EVA setup were checked against stock GPL ltq_umt_expand.c,
ltq_hwmcpy.c and ltq_hwmcpy_addr.h, with Intel's Linux 4.9 copies as a cross-check.
The endpoint MSG1 write matches stock writel; the current native MIPS build has
CONFIG_SWAP_IO_SPACE disabled, matching native-endian MCPY register accesses.

Validation completed in the isolated scratch build:

* Linux 6.18.55 vmlinux and all selected modules, including the latest five CGU
  gate registrations: compiled/linked successfully.
* directconnect_datapath.ko and dc_mode-hw.ko: compiled and passed real modpost
  against that kernel (no invented/stub symbol table).
* DC-enabled mtlk.ko and mtlkroot.ko, rebased on Wi-Fi baseline patch
  eca974b67dfa621b8dc5876273794ef1938c397a8f4a64992e8ae47e49aa0ba0:
  compiled and passed real modpost with the DirectConnect exports.
* Combined AX3000+UMT DTB compiled without dtc diagnostics.
* ``python3 tests/test-umt.py`` compiles the actual UMT functions from the patch
  against a deterministic MMIO/CBM harness. Port allocation/full/reuse, register
  fields, enable/suspend, periods, dequeue wrap, notification cap and timer
  gating passed. This does not emulate the hardware or concurrent IRQ timing.
* Kernel and Wi-Fi patches apply to the current baseline; the source patch
  applies to the pinned archive. The integration applier was exercised on a
  temporary checkout and preserves the default software-path autoload file.

The complete alternative OpenWrt build also passed, including both DirectConnect
APKs/modules and the DC-enabled Wi-Fi package. RAM and sysupgrade image audits
passed with ``--directconnect``: kernel/ELF binding, compiled clock gates, UMT
node/exports, installed DC modules and the unchanged software-path default.
``validation.json`` records that earlier build's integrated image/module hashes.
``current-rebase-audit.rst`` records the later full rebuild against the current
OpenWrt and AX3000 port, including Wi-Fi patches through 245 and fresh image audits.
OpenWrt moves
module symbol tables before InstallDev; the package exports the collected
``$(PKG_SYMVERS_DIR)/$(PKG_NAME).symvers`` for the dependent Wi-Fi build.
Real-device validation still needs boot/UMT counter progress, bidirectional traffic
on both bands, VLAN/STP/isolation and multicast tests, station add/remove/rekey,
firmware recovery and ring starvation under load. Timer jitter and achievable
throughput cannot be inferred from successful compilation or the host tests.
