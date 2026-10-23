#!/usr/bin/env python3
"""Apply the opt-in variant to an explicitly named OpenWrt checkout."""
import argparse, pathlib, shutil
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('openwrt',type=pathlib.Path,help='alternate OpenWrt checkout with the AX3000 port')
a=p.parse_args(); root=a.openwrt.resolve(); here=pathlib.Path(__file__).resolve().parent
wifi=root/'package/kernel/iwlwav-stock'; target=root/'target/linux/grx500'
assert (wifi/'Makefile').is_file() and (target/'config-6.18').is_file(), 'AX3000 baseline missing'
assert not (root/'package/kernel/directconnect-grx500').exists(), 'variant already applied'
# Validate all replacement anchors before modifying anything.
s=(wifi/'Makefile').read_text()
assert 'PKG_BUILD_PARALLEL:=1' in s and 'DEPENDS:=@TARGET_grx500 ' in s
needle='\t+$(KERNEL_MAKE) $(PKG_JOBS) M="$(PKG_BUILD_DIR)" modules'
assert needle in s
cfg=(wifi/'files/vendor-config.h').read_text(); assert '#undef MTCFG_DC_DP_LIB_SUPPORT' in cfg
shutil.copytree(here/'package/directconnect-grx500',root/'package/kernel/directconnect-grx500')
shutil.copy2(here/'170-grx500-directconnect.patch',target/'patches-6.18/170-grx500-directconnect.patch')
shutil.copy2(here/'grx500-umt.dtsi',target/'dts/grx500-umt.dtsi')
dts=target/'dts/grx350-tplink-archer-ax3000-v1.dts';dts.write_text(dts.read_text()+'\n#include "grx500-umt.dtsi"\n')
cfg_kernel=target/'config-6.18';cfg_kernel.write_text(cfg_kernel.read_text()+'\nCONFIG_GRX500_UMT=y\n')
shutil.copy2(here/'110-directconnect-wifi.patch',wifi/'patches/110-directconnect-wifi.patch')
s=s.replace('PKG_BUILD_PARALLEL:=1','PKG_BUILD_PARALLEL:=1\nPKG_BUILD_DEPENDS:=directconnect-grx500')
s=s.replace('DEPENDS:=@TARGET_grx500 ', 'DEPENDS:=@TARGET_grx500 +kmod-directconnect-grx500 ')
s=s.replace(needle,'''\t$(INSTALL_DIR) $(PKG_BUILD_DIR)/include/net
\t$(INSTALL_DATA) $(STAGING_DIR)/usr/include/net/directconnect_dp_api.h $(PKG_BUILD_DIR)/include/net/
\t+$(KERNEL_MAKE) $(PKG_JOBS) M="$(PKG_BUILD_DIR)" KBUILD_EXTRA_SYMBOLS="$(STAGING_DIR)/usr/lib/directconnect-grx500/Module.symvers" modules''')
(wifi/'Makefile').write_text(s)
(wifi/'files/vendor-config.h').write_text(cfg.replace('#undef MTCFG_DC_DP_LIB_SUPPORT','#define MTCFG_DC_DP_LIB_SUPPORT 1'))
k=wifi/'files/Kbuild';k.write_text(k.read_text()+'\nccflags-y += -DCONFIG_DIRECTCONNECT_DP_API=1 -I$(src)/include\n')
print('Applied optional DirectConnect variant to',root)
print('Run make defconfig, then the normal build. Wi-Fi fastpath remains0 by default.')
