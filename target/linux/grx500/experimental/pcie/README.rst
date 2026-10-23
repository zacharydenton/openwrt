GRX500 PCIe dependencies
=======================

The four source files implement the PCIe host, PHY, RCU reset controller and
GPIO input/output with GPIO pad selection for Linux 6.18.55. They compiled and
linked into the experimental MIPS kernel. The DTS compiled against the current
AX3000 board DTS. No hardware boot or enumeration has been observed.

Copy ``files/`` into the prepared kernel (or the target's ``files/`` overlay).
Source ``Kconfig.pcie`` from the target's architecture Kconfig, and add::

  drivers/pci/controller/Makefile: obj-$(CONFIG_PCIE_GRX500) += pcie-grx500.o
  drivers/phy/Makefile: obj-$(CONFIG_PHY_GRX500_PCIE) += intel/
  drivers/phy/intel/Makefile: obj-$(CONFIG_PHY_GRX500_PCIE) += phy-grx500-pcie.o
  drivers/reset/Makefile: obj-$(CONFIG_RESET_GRX500) += reset-grx500.o
  drivers/gpio/Makefile: obj-$(CONFIG_GPIO_GRX500) += gpio-grx500.o

Include ``grx500-pcie.dtsi`` after ``grx500.dtsi`` in the board DTS. It references
the existing cgu, rcu and gic labels and adds #reset-cells=2 to rcu. The reset
provider also supports GPHY reset bits at request register 0x10. Existing
syscon-reboot remains responsible for machine restart.

The host is adapted from Intel Linux commit
dc542d0ac6100123552c3a6ea12296061850e20b. ``adapt.py`` records the transformation;
its scratch relative path expects a sibling intel-linux checkout. Only GRX500
and legacy INTx are supported, matching the stock Wave600 configuration. MSI,
PCI I/O BARs, GPIO interrupts and other Intel SoCs are not advertised.

Important corrections derived from stock code and DTB:

* PCIe2 endpoint reset uses GPIO bank0 line14 active-high. PCIe0 and PCIe1 use
  bank1 lines11 and29 active-low. GPIO flags now encode actual polarity.
* Stock PHY mode5 means 100 MHz with SSC. All three PHYs share one LCPLL;
  programming is serialized, and lock/reset failures propagate to probe.
* MEM ranges use identity PCI/CPU addresses b4000000, b8000000 and bc000000.
  Stock pci_load_of_ranges ignored the PCI child-address cells, so copying
  those raw cells into a modern binding would offset BARs incorrectly.
* The fixed configuration aperture encodes only buses0–7. Bus8 would wrap.
* GPIO and pinpad registers use native-endian access, as stock does.
  The PHY syscons explicitly use native-endian regmap access.

The PHY avoids powering down its hardware on detach: the vendor documents that
doing so can halt the SoC. It gates the corresponding reference output and
leaves the shared PLL configured for other ports. GPIO ownership changes only
the requested pin's mux, preserving NAND/other pins configured by U-Boot.

The object build and full link used the existing network experiment's kernel
configuration (CONFIG_WERROR disabled for unrelated imported network warnings).
The four added objects emitted no compiler diagnostics. ``build-results.json``
records their exact hashes and the linked kernel hash.
