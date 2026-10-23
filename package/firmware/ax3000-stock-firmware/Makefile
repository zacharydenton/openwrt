# SPDX-License-Identifier: GPL-2.0-only
include $(TOPDIR)/rules.mk

PKG_NAME:=ax3000-stock-firmware
PKG_VERSION:=230831
PKG_RELEASE:=1
PKG_SOURCE:=Archer_AX3000_US_V1_230831.zip
PKG_SOURCE_URL:=https://static.tp-link.com/upload/firmware/2023/202309/20230906/
PKG_SOURCE_URL_FILE:=Archer%20AX3000%28US%29_V1_230831.zip
PKG_HASH:=6198caa78034f69a029b1e4009c2a69f4c36ea9e673e75338b50925543198846
PKG_LICENSE:=Proprietary

include $(INCLUDE_DIR)/package.mk

define Package/ax3000-stock-firmware
  SECTION:=firmware
  CATEGORY:=Firmware
  TITLE:=Archer AX3000 US V1 GPHY and WAVE600 firmware
  DEPENDS:=@TARGET_grx500
endef

define Package/ax3000-stock-firmware/description
 Firmware extracted from the identified TP-Link stock update for local
 AX3000 bring-up. This does not include per-device radio calibration.
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
	python3 $(CURDIR)/extract-update.py $(DL_DIR)/$(PKG_SOURCE) $(PKG_BUILD_DIR)/stock.bin
	python3 $(TOPDIR)/target/linux/grx500/experimental/firmware-audit/extract-stock.py \
		$(PKG_BUILD_DIR)/stock.bin $(PKG_BUILD_DIR)/components
	$(STAGING_DIR_HOST)/bin/unsquashfs4 -d $(PKG_BUILD_DIR)/rootfs $(PKG_BUILD_DIR)/components/rootfs.squashfs
endef

define Build/Compile
endef

define Package/ax3000-stock-firmware/install
	$(INSTALL_DIR) $(1)/lib/firmware
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/components/gphy-raw.bin $(1)/lib/firmware/ltq_fw_PHY11G_IP_xRx5xx_A21.bin
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/rootfs/lib/firmware/ap_ram_gen6_wrx_600_real_phy.bin $(1)/lib/firmware/
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/rootfs/lib/firmware/PSD.bin $(1)/lib/firmware/
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/rootfs/lib/firmware/ProgModel_gen6*.bin $(1)/lib/firmware/
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/rootfs/lib/firmware/host_interface_gen6*.bin $(1)/lib/firmware/
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/rootfs/lib/firmware/tx_sender_gen6*.bin $(1)/lib/firmware/
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/rootfs/lib/firmware/rx_handler_gen6*.bin $(1)/lib/firmware/
endef

$(eval $(call BuildPackage,ax3000-stock-firmware))
