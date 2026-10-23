# SPDX-License-Identifier: GPL-2.0-only
include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk

PKG_NAME:=iwlwav-stock
PKG_VERSION:=6.0.8.0.87.0.7
PKG_RELEASE:=1
PKG_SOURCE:=ax3000v1_GPL_3.tar.gz
PKG_SOURCE_URL:=https://static.tp-link.com/upload/gpl-code/2022/202211/20221107/
PKG_HASH:=de5befc72e4198e490ff4205439d4f8407175f92e487afc44071fd5a726be4c6
PKG_LICENSE:=GPL-2.0-only OR BSD-2-Clause
PKG_LICENSE_FILES:=LICENSE
PKG_BUILD_PARALLEL:=1

include $(INCLUDE_DIR)/package.mk

define KernelPackage/iwlwav-stock
  SUBMENU:=Wireless Drivers
  TITLE:=Intel WAVE600 stock ABI driver for Archer AX3000
  DEPENDS:=@TARGET_grx500 +ax3000-stock-firmware +wifi-scripts +wireless-regdb +@DRIVER_11N_SUPPORT +@DRIVER_11AC_SUPPORT +@DRIVER_11AX_SUPPORT
  FILES:=$(PKG_BUILD_DIR)/mtlkroot.ko $(PKG_BUILD_DIR)/mtlk.ko
  AUTOLOAD:=$(call AutoLoad,60,mtlkroot mtlk)
  MODPARAMS.mtlk:=fastpath=0,0,0 dual_pci=1,0 ahb_off=1 loggersid=255,255 rcvry_on=1,1
endef

define KernelPackage/iwlwav-stock/description
 Experimental native Linux 6.18 cfg80211/mac80211 port of the exact WAVE
 source matching the AX3000 stock firmware. Supports the software data
 path, HT/VHT/HE up to 160MHz, native SAE and PMF. Requires
 per-device calibration before loading. Hardware validation is pending.
 Native cfg80211/mac80211 are built into the GRX500 kernel; do not install
 the OpenWrt backports kmod-cfg80211/kmod-mac80211 alongside this driver.
endef

define KernelPackage/iwlwav-stock/install
	$(INSTALL_DIR) $(1)/etc/modules.d
	$(INSTALL_DATA) $(CURDIR)/autoload $(1)/etc/modules.d/60-iwlwav-stock
	$(INSTALL_DIR) $(1)/etc/hotplug.d/pci $(1)/usr/libexec
	$(INSTALL_DATA) $(CURDIR)/recovery/30-iwlwav-recovery $(1)/etc/hotplug.d/pci/30-iwlwav-recovery
	$(INSTALL_BIN) $(CURDIR)/recovery/iwlwav-recover $(1)/usr/libexec/iwlwav-recover
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
	python3 $(CURDIR)/extract-source.py $(DL_DIR)/$(PKG_SOURCE) $(PKG_BUILD_DIR)
	$(call Build/Patch)
	$(CP) $(CURDIR)/files/* $(PKG_BUILD_DIR)/
	python3 $(CURDIR)/prepare-logging.py $(PKG_BUILD_DIR)
endef

define Build/Configure
endef

define Build/Compile
	+$(KERNEL_MAKE) $(PKG_JOBS) M="$(PKG_BUILD_DIR)" modules
endef

$(eval $(call KernelPackage,iwlwav-stock))
