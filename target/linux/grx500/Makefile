# SPDX-License-Identifier: GPL-2.0-only

include $(TOPDIR)/rules.mk

ARCH:=mips
BOARD:=grx500
BOARDNAME:=Intel GRX500 (experimental)
CPU_TYPE:=24kc
SUBTARGETS:=generic
FEATURES:=ramdisk squashfs nand usb source-only
KERNEL_PATCHVER:=6.18

define Target/Description
	Experimental Intel GRX350/GRX500 device support.
endef

include $(INCLUDE_DIR)/target.mk

KERNELNAME:=vmlinux

$(eval $(call BuildTarget))
