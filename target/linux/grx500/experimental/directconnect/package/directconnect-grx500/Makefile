# SPDX-License-Identifier: GPL-2.0-only
include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk
PKG_NAME:=directconnect-grx500
PKG_VERSION:=5.0.7
PKG_RELEASE:=1
PKG_SOURCE_VERSION:=6ceb742215486e690c6c8604f06a81415d12f398
PKG_SOURCE:=directconnect_dp-$(PKG_SOURCE_VERSION).tar.gz
PKG_SOURCE_URL:=https://gitlab.com/prpl-foundation/intel/directconnect_dp/-/archive/$(PKG_SOURCE_VERSION)/
PKG_HASH:=d3bb1780a41a05bb8ad077a83456d91dc1e139e82c05c8bafbeb0fdf9a88e582
PKG_BUILD_DIR:=$(KERNEL_BUILD_DIR)/directconnect_dp-$(PKG_SOURCE_VERSION)
PKG_LICENSE:=GPL-2.0-only
PKG_BUILD_PARALLEL:=1
include $(INCLUDE_DIR)/package.mk

define KernelPackage/directconnect-grx500
  SUBMENU:=Network Devices
  TITLE:=Experimental GRX500 DirectConnect transport
  DEPENDS:=@TARGET_grx500
  KCONFIG:=CONFIG_GRX500_UMT=y
  FILES:=$(PKG_BUILD_DIR)/common/directconnect_datapath.ko $(PKG_BUILD_DIR)/dc_mode/dc_mode-hw.ko
  AUTOLOAD:=$(call AutoLoad,50,directconnect_datapath dc_mode-hw)
endef

define Build/Compile
	+$(KERNEL_MAKE) $(PKG_JOBS) M="$(PKG_BUILD_DIR)" CONFIG_DIRECTCONNECT_DP_XRX500=y modules
endef

define Build/InstallDev
	$(INSTALL_DIR) $(1)/usr/include/net $(1)/usr/lib/directconnect-grx500
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/include/directconnect_dp_api.h $(1)/usr/include/net/
	$(INSTALL_DATA) $(PKG_SYMVERS_DIR)/$(PKG_NAME).symvers $(1)/usr/lib/directconnect-grx500/Module.symvers
endef

$(eval $(call KernelPackage,directconnect-grx500))
