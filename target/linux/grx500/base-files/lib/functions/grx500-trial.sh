#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Experimental first-boot transaction. Leaf functions are isolated by tests.

grx500_trial_bank() {
	cat /proc/cmdline | awk '
		{ for (i=1; i<=NF; i++) if ($i ~ /^rootfsname=/) {
			n++; if ($i == "rootfsname=rootfsA") b="A";
			else if ($i == "rootfsname=rootfsB") b="B"; else bad=1
		} }
		END { if (n!=1 || bad) exit 1; print b }
	'
}

grx500_trial_config() {
	local name index offset
	for name in ubootconfigA ubootconfigB; do
		index="$(find_mtd_index "$name")"
		case "$index" in ''|*[!0-9]*) return 1;; esac
		[ "$name" = ubootconfigA ] && offset=1048576 || offset=1310720
		[ "$(cat /sys/class/mtd/mtd$index/offset)" = "$offset" ] &&
		[ "$(cat /sys/class/mtd/mtd$index/size)" = 262144 ] &&
		[ "$(cat /sys/class/mtd/mtd$index/erasesize)" = 131072 ] &&
		[ "$(cat /sys/class/mtd/mtd$index/writesize)" = 2048 ] &&
		[ "$(cat /sys/class/mtd/mtd$index/type)" = nand ] &&
		[ -c "/dev/mtd$index" ] || return 1
		printf '/dev/mtd%s 0 0x4000 0x20000 2\n' "$index"
	done
}

grx500_trial_value() {
	fw_printenv -c "$GRX500_TRIAL_CONFIG" -n "$1"
}

grx500_trial_contract() {
	local line name expected actual count=0
	while IFS= read -r line; do
		name="${line%%=*}"; expected="${line#*=}"
		[ -n "$name" ] && [ "$line" != "$name" ] || return 1
		actual="$(grx500_trial_value "$name")" || return 1
		# The shipped addmisc default has one trailing space absent in sdk.config.
		# Permit that insignificant terminator; retain all internal command bytes.
		actual="${actual% }"
		[ "$actual" = "$expected" ] || return 1
		count=$((count + 1))
	done < /etc/grx500-boot-contract
	[ "$count" = 13 ]
}

grx500_trial_context() {
	local state
	[ "$(board_name)" = "tplink,archer-ax3000-v1" ] || return 1
	GRX500_TRIAL_BANK="$(grx500_trial_bank)" || return 1
	state="$(grx500_trial_value update_chk)" || return 1
	case "$state:$GRX500_TRIAL_BANK" in
		0:A|2:B) return 2;; # Already stable, no transaction.
		0:B) GRX500_TRIAL_OLD=A; GRX500_TRIAL_STATE=0; GRX500_TRIAL_NEW=2;;
		2:A) GRX500_TRIAL_OLD=B; GRX500_TRIAL_STATE=2; GRX500_TRIAL_NEW=0;;
		*) return 1;;
	esac
	grx500_trial_contract || return 1
	[ "$(grx500_trial_value active_bank)" = "$GRX500_TRIAL_BANK" ] || return 1
}

grx500_trial_root() {
	local mountpoint="$1" volume="$2" dev
	dev="$(cat "/sys/class/block/ubiblock${volume#ubi}/dev")" || return 1
	awk -v mp="$mountpoint" -v dev="$dev" '
		$5==mp && $3==dev { for(i=7;i<=NF;i++) if($i=="-" && $(i+1)=="squashfs") n++ }
		END { exit n!=1 }
	' /proc/self/mountinfo
}

grx500_trial_volume_context() {
	local index name volume
	index="$(grx500_factory_system_mtd)" || return 1
	GRX500_TRIAL_UBI="$(nand_find_ubi system_sw)"
	[ -n "$GRX500_TRIAL_UBI" ] &&
	[ "$(cat /sys/class/ubi/$GRX500_TRIAL_UBI/mtd_num)" = "$index" ] || return 1
	for name in kernelA kernelB rootfsA rootfsB bootcoreA bootcoreB; do
		volume="$(nand_find_volume "$GRX500_TRIAL_UBI" "$name")"
		[ -n "$volume" ] || return 1
	done
	GRX500_TRIAL_ROOT="$(nand_find_volume "$GRX500_TRIAL_UBI" "rootfs$GRX500_TRIAL_BANK")"
}

grx500_trial_prepare() {
	local result leb free needed volume stock_data
	grx500_trial_context; result=$?
	[ "$result" = 2 ] && return 0
	[ "$result" = 0 ] || return 1
	grx500_trial_writable || return 1
	grx500_trial_volume_context && grx500_trial_root / "$GRX500_TRIAL_ROOT" || return 1
	# Never reuse or delete an existing overlay/staging volume on stock migration.
	[ -z "$(nand_find_volume "$GRX500_TRIAL_UBI" rootfs_data)" ] &&
	[ -z "$(nand_find_volume "$GRX500_TRIAL_UBI" openwrt-trial-data)" ] || return 1
	leb="$(cat /sys/class/ubi/$GRX500_TRIAL_UBI/eraseblock_size)" || return 1
	free="$(cat /sys/class/ubi/$GRX500_TRIAL_UBI/avail_eraseblocks)" || return 1
	case "$leb:$free" in *[!0-9:]*|:*|*:) return 1;; esac
	[ "$leb" = 126976 ] || return 1
	needed=$(( (8388608 + leb - 1) / leb ))
	# Stock preinit mounts data_vol and creates it at 20 MiB when absent.
	# A failed OpenWrt trial must leave that capacity available for fallback.
	stock_data="$(nand_find_volume "$GRX500_TRIAL_UBI" data_vol)"
	[ -n "$stock_data" ] ||
		needed=$((needed + (20971520 + leb - 1) / leb))
	[ "$free" -ge "$needed" ] || return 1
	ubimkvol "/dev/$GRX500_TRIAL_UBI" -N openwrt-trial-data -s 8MiB || return 1
	volume="$(nand_find_volume "$GRX500_TRIAL_UBI" openwrt-trial-data)"
	[ -n "$volume" ] || return 1
	mkdir -p /tmp/grx500-trial-overlay || return 1
	mount -t ubifs "/dev/$volume" /tmp/grx500-trial-overlay || return 1
	printf 'AX3000-US-V1-TRIAL-1 %s\n' "$GRX500_TRIAL_BANK" > /tmp/grx500-trial-overlay/.ax3000-trial || {
		umount /tmp/grx500-trial-overlay; return 1
	}
	sync
	umount /tmp/grx500-trial-overlay || return 1
	ubirename "/dev/$GRX500_TRIAL_UBI" openwrt-trial-data rootfs_data || return 1
	printf '%s\n' "$GRX500_TRIAL_BANK" > /tmp/grx500-trial-pending
}

grx500_trial_writable() {
	local name index flags
	for name in ubootconfigA ubootconfigB; do
		index="$(find_mtd_index "$name")"
		case "$index" in ''|*[!0-9]*) return 1;; esac
		flags="$(cat /sys/class/mtd/mtd$index/flags)" || return 1
		case "$flags" in 0x*) ;; *) return 1;; esac
		case "${flags#0x}" in ''|*[!0-9a-fA-F]*) return 1;; esac
		[ "$((flags & 0x400))" = 1024 ] || return 1
	done
}

grx500_trial_health() {
	local port phy count=0 mac state volume
	[ "$(cat /overlay/.ax3000-trial)" = "AX3000-US-V1-TRIAL-1 $GRX500_TRIAL_BANK" ] || return 1
	volume="$(nand_find_volume "$GRX500_TRIAL_UBI" rootfs_data)"
	[ -n "$volume" ] || return 1
	awk -v dev="/dev/$volume" -v named="$GRX500_TRIAL_UBI:rootfs_data" '
		$2=="/overlay" && $3=="ubifs" && ($1==dev || $1==named) {n++}
		END {exit n!=1}
	' /proc/mounts || return 1
	grx500_trial_root /rom "$GRX500_TRIAL_ROOT" || return 1
	mac="$(grx500_factory_parse_mac /tmp/grx500-factory-mac)" || return 1
	[ "$(cat /sys/class/net/br-lan/address)" = "$mac" ] || return 1
	for port in lan1 lan2 lan3 lan4; do
		[ "$(basename "$(readlink /sys/class/net/$port/brport/bridge)")" = br-lan ] || return 1
	done
	[ -d /sys/class/net/wan ] && [ ! -e /sys/class/net/wan/brport ] || return 1
	[ "$(cat /sys/class/net/br-lan/carrier)" = 1 ] || return 1
	state="$(ubus call network.interface.lan status)" || return 1
	[ "$(printf '%s' "$state" | jsonfilter -e '@.up')" = true ] || return 1
	pidof dnsmasq >/dev/null && pidof dropbear >/dev/null || return 1
	for phy in /sys/class/ieee80211/phy*; do
		[ -d "$phy" ] || continue
		iw phy "${phy##*/}" info >/dev/null || return 1
		count=$((count + 1))
	done
	[ "$count" = 2 ] || return 1
	for port in 0 2; do
		[ -s "/lib/firmware/cal_wlan$port.bin" ] || return 1
	done
	# Probe persistent storage before changing the boot decision.
	printf 'ready\n' > /overlay/.ax3000-write-probe && sync &&
	[ "$(cat /overlay/.ax3000-write-probe)" = ready ]
}

grx500_trial_acceptance() {
	local boot_id accepted
	# Startup prerequisites are not device acceptance. Only an explicit
	# root action after testing this boot may authorize the bank transaction.
	# The marker is in tmpfs and bound to this boot and the running bank.
	boot_id="$(cat /proc/sys/kernel/random/boot_id)" || return 1
	[ -n "$boot_id" ] || return 1
	accepted="$(cat /tmp/grx500-trial-accept 2>/dev/null)" || return 1
	[ "$accepted" = "AX3000-US-V1-ACCEPT-1 $GRX500_TRIAL_BANK $boot_id" ]
}

grx500_trial_commit() (
	local bank result batch
	# A rejection and the environment transaction must have one ordering.
	# Hold the lock through the save and readback; a late rejection then sees
	# that the pending marker has gone and cannot promise a stock fallback.
	exec 9<>/tmp/grx500-trial-lock/decision.lock || return 1
	flock -x 9 || return 1
	[ ! -e /tmp/grx500-trial-failed ] || return 1
	[ ! -e /tmp/grx500-trial-commit-started ] || return 1
	bank="$(cat /tmp/grx500-trial-pending)" || return 1
	grx500_trial_context || return 1
	[ "$bank" = "$GRX500_TRIAL_BANK" ] || return 1
	grx500_trial_writable || return 1
	grx500_trial_volume_context && grx500_trial_health || return 1
	grx500_trial_acceptance || return 1
	batch="$(mktemp /tmp/grx500-commit.XXXXXX)" || return 1
	printf 'update_chk %s\nactive_bank %s\n' "$GRX500_TRIAL_NEW" "$GRX500_TRIAL_BANK" > "$batch"
	# A failed or interrupted save leaves the boot decision uncertain. Keep
	# manual rejection from promising fallback after a save was attempted.
	touch /tmp/grx500-trial-commit-started || { rm -f "$batch"; return 1; }
	# A single redundant-environment save replaces three independent stock saves.
	fw_setenv -c "$GRX500_TRIAL_CONFIG" -s "$batch"; result=$?
	rm -f "$batch"
	[ "$result" = 0 ] || return 1
	[ "$(grx500_trial_value update_chk)" = "$GRX500_TRIAL_NEW" ] &&
	[ "$(grx500_trial_value active_bank)" = "$GRX500_TRIAL_BANK" ] || return 1
	printf 'committed %s\n' "$GRX500_TRIAL_BANK" > /overlay/.ax3000-trial-status
	sync
	rm -f /tmp/grx500-trial-pending
)
