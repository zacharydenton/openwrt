# SPDX-License-Identifier: GPL-2.0-only

include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/image.mk

DTS_DIR := ../dts
KERNEL_LOADADDR := 0xa0020000
AX3000_LOADER_DIR := $(TOPDIR)/target/linux/grx500/experimental/firmware-audit

# Stock flash boot reads at 0x80800000. Direct LZMA expansion to 0xa0020000
# overlaps that input for these kernels. Keep the intermediate ELF for audit.
define Build/ax3000-relocate-kernel
	rm -rf "$@.relocated"
	$(STAGING_DIR_HOST)/bin/python3 $(AX3000_LOADER_DIR)/build-relocated-kernel.py \
		--openwrt $(TOPDIR) --kernel "$@" --output "$@.relocated" \
		> "$@.relocated.json"
	cp "$@.relocated/kernel.uimage" "$@"
endef

define Build/ax3000-add-checksums
	$(STAGING_DIR_HOST)/bin/python3 $(TOPDIR)/target/linux/grx500/image/append-sysupgrade-checksums.py "$@"
endef

define Device/Default
  PROFILES := Default
  KERNEL := kernel-bin | append-dtb | lzma | uImage lzma | ax3000-relocate-kernel
  KERNEL_INITRAMFS := kernel-bin | append-dtb | lzma | uImage lzma | ax3000-relocate-kernel
  KERNEL_DEPENDS = $$(wildcard $(DTS_DIR)/$$(DEVICE_DTS).dts) $(wildcard $(AX3000_LOADER_DIR)/relocated-kernel.*) $(AX3000_LOADER_DIR)/build-relocated-kernel.py $(wildcard $(TOPDIR)/target/linux/lantiq/image/lzma-loader/src/Lzma*)
  BLOCKSIZE := 128k
  PAGESIZE := 2048
  KERNEL_IN_UBI := 1
  IMAGES := sysupgrade.bin
  IMAGE/sysupgrade.bin := sysupgrade-tar | ax3000-add-checksums | append-metadata
endef

define Device/tplink_archer-ax3000-v1
  DEVICE_VENDOR := TP-Link
  DEVICE_MODEL := Archer AX3000
  DEVICE_VARIANT := v1 (US, including v1.6)
  DEVICE_PACKAGES := grx500-factory kmod-usb-storage kmod-usb-storage-uas kmod-usb-ledtrig-usbport kmod-fs-vfat kmod-fs-exfat kmod-fs-ext4 kmod-fs-ntfs3 block-mount kmod-iwlwav-stock ubi-utils uboot-envtools ax3000-stock-firmware kmod-gpio-button-hotplug nand-utils wifi-scripts iw wpad-mbedtls hostapd-utils wireless-regdb
  DEVICE_DTS := grx350-tplink-archer-ax3000-v1
endef
TARGET_DEVICES += tplink_archer-ax3000-v1

$(eval $(call BuildImage))
