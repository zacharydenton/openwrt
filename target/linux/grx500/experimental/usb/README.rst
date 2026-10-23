GRX500 USB host integration for Linux 6.18
========================================

Evidence and board selection
----------------------------

The actual AX3000(US) V1 230831 DTB describes two DWC3 controllers:

* USB0: core1a300000, PHY1a400000, clock108, shared IRQ54, RCU48 bit4,
  VBUS/overcurrent GPIO0.14, overcurrent shared IRQ53.
* USB1: core1a500000, PHY1a600000, clock124, shared IRQ83, RCU48 bit5,
  VBUS/overcurrent GPIO0.2, overcurrent shared IRQ50.

The old DT IRQ values include eight CPU-local interrupts; the modern shared
GIC interrupt numbers above subtract eight. The OC IRQ is active-low level.
The exact stock LED is named blue:usb_2 on GPIO0.11. The official US V1 manual
shows one external USB connector. These facts favor USB1, but the connector
mapping requires hardware confirmation. USB0 is deliberately omitted: its
VBUS GPIO0.14 is also the third PCIe endpoint reset. All three stock PCIe
connections are retained for the two Wave600 radios (stock dual_pci=1,0).

Stock GPL sources under intel_GRX350/sdk/7.5.1.50/ugw/target/linux/lantiq/
linux-3.10.104-sources supply the hardware sequences:

* drivers/usb/dwc3/dwc3-ltq.c: USB clock enable,100ms; chiptop host endian,
  100ms; PHY reset release,100ms; CONFIG_TP_IMAGE drives VBUS low.
* The source tree's root Makefile unconditionally defines CONFIG_TP_IMAGE.
  Thus GPIO0.2 is active-low power enable despite its raw stock DT flags0.
* drivers/usb/phy/phy-ltq-dwc3.c: optional TX inversion at PHY+4000 bit3 and
  RX inversion at PHY+4014 bit1. Neither inversion is set in this board DT.
* drivers/usb/dwc3/ltq-usb-oc.c: pad mux3 engages hardware overcurrent
  protection. Recovery after30s switches to GPIO mode for10ms, then back to
  mux3 for10ms. The new driver masks the level IRQ during the retry interval;
  a fatal mux error turns VBUS off, attempts GPIO mode, and asserts PHY reset.

Intel Linux4.9 commit dc542d0ac6100123552c3a6ea12296061850e20b also contains
modernized dwc3-grx500.c and phy-grx500-usb.c. The new glue uses Linux6.18's
embedded dwc3_probe_data API, rather than creating an obsolete child device.
The PHY handles reset, power and OC work with managed resources and bounded
sleeps. Suspend/resume delegates core sequencing before changing the clock.

Endianness audit
----------------

The stock and Intel4.9 glue both set chiptop HOST_END bit10 and clear DEV_END
bit9 (USB1 register16080034). This configures host AXI big endian and device
little endian. The MIPS target has CONFIG_SWAP_IO_SPACE disabled, so readl
and writel are native accesses; syscon maps explicitly use native-endian.

Stock xhci.h defines its memory-register MSWAP helper but detects whether it
is needed from HC_CAPBASE at runtime (xhci.c near4750); no captured runtime
result is available. Its separate descriptor SSWAP path is explicitly
undefined unless __LQ_XHCI_CIP__ is set; CIP is not defined. Consequently the
stock descriptor macros reduce to ordinary cpu_to_le32/cpu_to_le64 and
le32_to_cpu/le64_to_cpu, just as in Linux6.18. No descriptor byte-swap patches
are added. Intel4.9 uses the same endian syscon sequence with normal xHCI
accessors, supporting this choice. Native MMIO is also checked by DWC3's
existing GSNPSID validation. Enumeration remains a hardware test, not a
consequence proved by compilation or the stock sources alone.

Integration
-----------

Copy files/ over the prepared kernel overlay. Add Kconfig.usb to a Kconfig
source reachable for INTEL_MIPS (or append it to the target's existing
architecture Kconfig additions). Add these Makefile entries::

  drivers/usb/dwc3/Makefile:
    obj-$(CONFIG_USB_DWC3_GRX500) += dwc3-grx500.o
  drivers/phy/intel/Makefile:
    obj-$(CONFIG_PHY_GRX500_USB) += phy-grx500-usb.o

The existing generic PHY Makefile already enters intel/ when GENERIC_PHY is
enabled; the existing PCIe target hook also enters it. No additional directory
hook is needed. Enable USB_SUPPORT, USB, USB_XHCI_HCD, USB_XHCI_PLATFORM,
USB_DWC3, USB_DWC3_HOST, USB_DWC3_GRX500 and PHY_GRX500_USB built-in. The PHY
requires existing GPIOLIB and RESET_CONTROLLER. Include grx500-usb.dtsi after
grx500-pcie.dtsi, which provides GPIO, RCU and chiptop labels. USB storage/UAS
and filesystems are separate OpenWrt packages selected in the device profile.

The pad syscon shares the existing GPIO bank's pad register mapping. GPIO
ownership reserves pin2; PHY mux changes affect only that pin's low three
bits, preserving the other GPIO/PCIe/LED pads. The GPIO output latch is set
inactive before entering GPIO mode on shutdown and initialization failure.

Validation
----------

The two new drivers, DWC3 core and host glue cross-compile for big-endian
MIPS Linux6.18 without new compiler warnings. The full board with the new
USB include compiles with dtc without warnings. build-results.json records
the subsequent isolated vmlinux link result. Physical port routing, voltage,
overcurrent response, suspend/resume and USB device enumeration are untested.
