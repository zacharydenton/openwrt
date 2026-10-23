include $(TOPDIR)/rules.mk

PKG_NAME:=grx500-factory
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only

include $(INCLUDE_DIR)/package.mk

define Package/grx500-factory
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=GRX500 factory UBI attachment guard
  DEPENDS:=@TARGET_grx500 +ubi-utils
endef

define Package/grx500-factory-install
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=Experimental AX3000 stock-web first-boot transaction
  DEPENDS:=grx500-factory +uboot-envtools +jsonfilter +iw
endef

define Package/grx500-factory-install/install
	$(INSTALL_DIR) $(1)/etc
	touch $(1)/etc/grx500-factory-install
	$(INSTALL_DIR) $(1)/usr/sbin
	$(INSTALL_BIN) ./files/grx500-trialctl $(1)/usr/sbin/
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/* $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(TARGET_CC) $(TARGET_CFLAGS) $(TARGET_CPPFLAGS) -Wall -Wextra \
		-o $(PKG_BUILD_DIR)/grx500-check-ubi $(PKG_BUILD_DIR)/grx500-check-ubi.c $(TARGET_LDFLAGS)
endef

define Package/grx500-factory/install
	$(INSTALL_DIR) $(1)/usr/sbin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/grx500-check-ubi $(1)/usr/sbin/
endef

$(eval $(call BuildPackage,grx500-factory))
$(eval $(call BuildPackage,grx500-factory-install))
