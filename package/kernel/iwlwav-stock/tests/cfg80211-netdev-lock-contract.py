#!/usr/bin/env python3
"""Check the driver against the target kernel's cfg80211 netdev lock contract."""

import argparse
from pathlib import Path
import re


def function(source: str, name: str) -> str:
    for match in re.finditer(r"\b" + re.escape(name) + r"\s*\(", source):
        depth = 1
        pos = match.end()
        while depth and pos < len(source):
            depth += (source[pos] == "(") - (source[pos] == ")")
            pos += 1
        if source[pos:].lstrip().startswith("{"):
            start = source.rfind("\n", 0, match.start() - 1) + 1
            end = source.find("\n}", pos)
            if end < 0:
                raise AssertionError(f"unterminated {name}")
            return source[start : end + 2]
    raise AssertionError(f"missing {name}")


def require(source: str, *patterns: str) -> None:
    for pattern in patterns:
        if not re.search(pattern, source, re.S):
            raise AssertionError(f"missing contract: {pattern}")


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("driver", type=Path, help="prepared iwlwav-stock source directory")
parser.add_argument("kernel", type=Path, help="target Linux source directory")
args = parser.parse_args()
drv = args.driver / "wireless/driver/linux"
wireless = args.kernel / "net/wireless"

nl = (wireless / "nl80211.c").read_text()
core = (wireless / "core.c").read_text()
api = (args.kernel / "include/net/cfg80211.h").read_text()
cfg = (drv / "cfg80211.c").read_text()
df = (drv / "mtlk_df_user.c").read_text()
vap = (drv / "core.c").read_text()
wext = (wireless / "wext-core.c").read_text()

vendor_op_match = re.search(
    r"\{\s*\.cmd\s*=\s*NL80211_CMD_VENDOR,.*?\n\t\},", nl, re.S
)
if not vendor_op_match:
    raise AssertionError("missing NL80211_CMD_VENDOR operation")
vendor_op = vendor_op_match.group(0)

require(vendor_op,
        r"\.doit\s*=\s*nl80211_vendor_cmd",
        r"NL80211_FLAG_NEED_WIPHY")
if "NL80211_FLAG_NO_WIPHY_MTX" in vendor_op:
    raise AssertionError("vendor command unexpectedly bypasses the wiphy mutex")
require(function(nl, "nl80211_pre_doit"),
        r"wiphy_lock\(&rdev->wiphy\).*"
        r"!\(internal_flags & NL80211_FLAG_NEED_RTNL\).*rtnl_unlock\(\)")
require(function(nl, "nl80211_vendor_cmd"),
        r"vcmd->doit\(&rdev->wiphy, wdev, data, len\)")
require(function(nl, "nl80211_post_doit"),
        r"wiphy_unlock\(&rdev->wiphy\)")

require(function(nl, "nl80211_new_interface"),
        r"guard\(wiphy\).*_nl80211_new_interface")
require(function(nl, "nl80211_del_interface"),
        r"dev_close\(wdev->netdev\).*mutex_lock\(&rdev->wiphy.mtx\).*cfg80211_remove_virtual_intf")
require(nl, r"NL80211_CMD_NEW_INTERFACE.*NL80211_FLAG_NEED_RTNL",
        r"NL80211_CMD_DEL_INTERFACE.*NL80211_FLAG_NEED_RTNL")
require(function(core, "cfg80211_register_netdevice"),
        r"lockdep_assert_held\(&rdev->wiphy.mtx\)",
        r"wdev->registering = true.*register_netdevice\(dev\)")
require(function(core, "cfg80211_unregister_wdev"),
        r"_cfg80211_unregister_wdev\(wdev, true\)")
require(api, r"cfg80211_unregister_netdevice.*cfg80211_unregister_wdev\(dev->ieee80211_ptr\)")
require(function(wext, "wext_ioctl_dispatch"),
        r"rtnl_lock\(\).*wireless_process_ioctl.*rtnl_unlock\(\)")

require(function(cfg, "wv_cfg80211_netdev_api_owner"),
        r"READ_ONCE\(cfg80211->netdev_api_owner\) == current")
for name, call in (("_wave_cfg80211_op_add_virtual_iface", "wave_radio_virtual_interface_add"),
                   ("_wave_cfg80211_op_del_virtual_iface", "wave_radio_virtual_interface_del")):
    require(function(cfg, name),
            rf"WRITE_ONCE\(cfg80211->netdev_api_owner, current\).*{call}.*"
            r"WRITE_ONCE\(cfg80211->netdev_api_owner, NULL\)")
require(function(df, "_mtlk_df_user_reg_netdev"),
        r"wv_cfg80211_netdev_api_owner.*cfg80211_register_netdevice.*else.*register_netdevice")
require(function(df, "_mtlk_df_user_unreg_netdev"),
        r"wv_cfg80211_netdev_api_owner.*cfg80211_unregister_netdevice.*else.*unregister_netdevice")
require(function(vap, "_mtlk_core_mbss_add_vap_idx"),
        r"mtlk_vap_manager_create_vap.*wv_cfg80211_wiphy_get")

print("PASS: cfg80211 callback and netdev lock contracts match the target kernel")
