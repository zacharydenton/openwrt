PART_NAME=none
REQUIRE_IMAGE_METADATA=1
RAMFS_COPY_BIN="mktemp sha256sum grx500-check-ubi fw_printenv ubiattach ubimkvol ubirmvol ubiupdatevol ubirename ubiblock"

grx500_upgrade_bank() {
	local state index config name result bank running offset
	# Redundant 16 KiB environments in separate 256 KiB NAND partitions.
	config="$(mktemp /tmp/grx500-env.XXXXXX)" || return 1
	for name in ubootconfigA ubootconfigB; do
		index="$(find_mtd_index "$name")"
		case "$index" in ''|*[!0-9]*) rm -f "$config"; return 1;; esac
		[ "$name" = ubootconfigA ] && offset=1048576 || offset=1310720
		[ "$(cat "/sys/class/mtd/mtd$index/offset")" = "$offset" ] &&
		[ "$(cat "/sys/class/mtd/mtd$index/size")" = 262144 ] &&
		[ "$(cat "/sys/class/mtd/mtd$index/erasesize")" = 131072 ] &&
		[ "$(cat "/sys/class/mtd/mtd$index/writesize")" = 2048 ] &&
		[ "$(cat "/sys/class/mtd/mtd$index/type")" = nand ] || {
			echo "Unexpected AX3000 boot environment partition geometry: $name" >&2
			rm -f "$config"
			return 1
		}
		echo "/dev/mtd$index 0x0 0x4000 0x20000 2" >> "$config"
	done
	state="$(fw_printenv -c "$config" -n update_chk)"
	result=$?
	rm -f "$config"
	[ "$result" = 0 ] || return 1
	# 1 and 3 are pending stock one-shot trial boots, not stable banks.
	case "$state" in
		0) bank=A;;
		2) bank=B;;
		*) echo "Unsupported or pending stock boot state: $state" >&2; return 1;;
	esac
	# Stock U-Boot restores the OLD stable state before booting a trial bank.
	# Saved update_chk alone would select and overwrite that stock fallback.
	running="$(cat /proc/cmdline | awk '
		{ for (i=1; i<=NF; i++) if ($i ~ /^rootfsname=/) {
			n++; if ($i == "rootfsname=rootfsA") bank="A";
			else if ($i == "rootfsname=rootfsB") bank="B"; else bad=1
		} }
		END { if (n != 1 || bad) exit 1; print bank }
	')" || return 1
	[ "$running" = "$bank" ] || {
		echo "Running bank differs from the saved stable bank; refusing to overwrite the stock fallback." >&2
		return 1
	}
	echo "$bank"
}

platform_check_image() {
	[ "$(board_name)" = "tplink,archer-ax3000-v1" ] || return 1
	local members
	members="$(tar -tf "$1" 2>/dev/null | awk '
		$0 == "sysupgrade-tplink_archer-ax3000-v1/kernel" { k++ }
		$0 == "sysupgrade-tplink_archer-ax3000-v1/root" { r++ }
		$0 == "sysupgrade-tplink_archer-ax3000-v1/SHA256SUMS" { s++ }
		END { print k ":" r ":" s }
	')"
	[ "$members" = "1:1:1" ] || {
		echo "Use an AX3000 sysupgrade archive with one kernel, rootfs and checksum member."
		return 1
	}
	[ "$(get_magic_long_tar "$1" cat sysupgrade-tplink_archer-ax3000-v1/kernel)" = 27051956 ] || return 1
	[ "$(get_magic_long_tar "$1" cat sysupgrade-tplink_archer-ax3000-v1/root)" = 68737173 ] || return 1
	grx500_upgrade_checksums "$1" || return 1
	nand_do_platform_check "$(board_name)" "$1" || return 1
	grx500_upgrade_bank >/dev/null || return 1
}

grx500_upgrade_checksums() {
	local image="$1" dir hashes kernel_hash root_hash
	dir=sysupgrade-tplink_archer-ax3000-v1
	hashes="$(tar -xOf "$image" "$dir/SHA256SUMS" | awk '
		NF == 2 && $1 == "kernel" && length($2) == 64 && $2 !~ /[^0-9a-f]/ { k++; kh=$2; next }
		NF == 2 && $1 == "root" && length($2) == 64 && $2 !~ /[^0-9a-f]/ { r++; rh=$2; next }
		{ bad=1 }
		END { if (k != 1 || r != 1 || bad) exit 1; print kh " " rh }
	')" || return 1
	kernel_hash="${hashes%% *}"; root_hash="${hashes#* }"
	[ -n "$kernel_hash" ] && [ -n "$root_hash" ] || return 1
	[ "$(tar -xOf "$image" "$dir/kernel" | sha256sum | awk '{print $1}')" = "$kernel_hash" ] &&
	[ "$(tar -xOf "$image" "$dir/root" | sha256sum | awk '{print $1}')" = "$root_hash" ] || {
		echo "AX3000 sysupgrade payload checksum mismatch." >&2
		return 1
	}
}

# Ubinize uses image-sized volumes and stock upgrades can create additional
# banks/config volumes. Only the live UBI accounting can establish free space;
# avail_eraseblocks already excludes UBI's bad-block and internal reserves.
grx500_upgrade_space() {
	local ubi="$1" kernel_length="$2" root_length="$3"
	local leb available needed reclaim=0 name volume blocks
	leb="$(cat "/sys/class/ubi/$ubi/eraseblock_size")" || return 1
	available="$(cat "/sys/class/ubi/$ubi/avail_eraseblocks")" || return 1
	case "$leb:$available" in *[!0-9:]*|:*|*:) return 1;; esac
	[ "$leb" -gt 0 ] && [ "$leb" -le 131072 ] || return 1
	for name in openwrt-new-kernel openwrt-new-rootfs openwrt-new-data \
		openwrt-backup-kernel openwrt-backup-rootfs openwrt-backup-data; do
		volume="$(nand_find_volume "$ubi" "$name")"
		[ -n "$volume" ] || continue
		blocks="$(cat "/sys/class/ubi/$volume/reserved_ebs")" || return 1
		case "$blocks" in ''|*[!0-9]*) return 1;; esac
		reclaim=$((reclaim + blocks))
	done
	needed=$(( (kernel_length + leb - 1) / leb + (root_length + leb - 1) / leb + (8388608 + leb - 1) / leb ))
	if [ "$needed" -gt "$((available + reclaim))" ]; then
		echo "Insufficient UBI staging space: need $needed eraseblocks, have $available free plus $reclaim old staging/backup blocks." >&2
		echo "Active bank, alternate bank and bootcore will not be removed or resized." >&2
		return 1
	fi
}

grx500_stage_volume() {
	local ubi="$1" name="$2" length="$3" image="$4" member="$5" volume
	ubimkvol "/dev/$ubi" -N "$name" -s "$length" || return 1
	volume="$(nand_find_volume "$ubi" "$name")"
	[ -n "$volume" ] || return 1
	tar -xOf "$image" "$member" | ubiupdatevol "/dev/$volume" -s "$length" -
}

grx500_upgrade_tar() {
	local image="$1" bank index ubi dir kernel_length root_length name volume
	# Recheck archive structure even if generic sysupgrade was forced.
	platform_check_image "$image" || return 1
	bank="$(grx500_upgrade_bank)" || return 1
	index="$(find_mtd_index system_sw)"
	case "$index" in ''|*[!0-9]*) return 1;; esac
	[ "$(cat /sys/class/mtd/mtd$index/size)" = 130023424 ] || return 1
	ubi="$(nand_find_ubi system_sw)"
	if [ -z "$ubi" ]; then
		# UBI can initialize blank NAND on attach; require the stock table first.
		grx500-check-ubi "/dev/mtd$index" || return 1
		ubiattach -m "$index" || return 1
		ubi="$(nand_find_ubi system_sw)"
	fi
	[ -n "$ubi" ] || return 1
	# Never format system_sw: it also contains bootcore and stock banks.
	for name in "kernel$bank" "rootfs$bank" "bootcore$bank"; do
		[ -n "$(nand_find_volume "$ubi" "$name")" ] || return 1
	done
	dir="sysupgrade-tplink_archer-ax3000-v1"
	kernel_length="$(tar -xOf "$image" "$dir/kernel" | wc -c)"
	root_length="$(tar -xOf "$image" "$dir/root" | wc -c)"
	[ "$kernel_length" -gt 64 ] && [ "$root_length" -gt 4096 ] &&
		[ "$kernel_length" -lt 130023424 ] && [ "$root_length" -lt 130023424 ] || return 1
	grx500_upgrade_space "$ubi" "$kernel_length" "$root_length" || return 1
	# Only remove abandoned staging and the previous OpenWrt backup.
	# Current kernel/rootfs and the other stock bank survive preparation errors.
	for name in openwrt-new-kernel openwrt-new-rootfs openwrt-new-data \
		openwrt-backup-kernel openwrt-backup-rootfs openwrt-backup-data; do
		volume="$(nand_find_volume "$ubi" "$name")"
		[ -z "$volume" ] || ubirmvol "/dev/$ubi" -N "$name" || return 1
	done
	grx500_stage_volume "$ubi" openwrt-new-kernel "$kernel_length" "$image" "$dir/kernel" || return 1
	grx500_stage_volume "$ubi" openwrt-new-rootfs "$root_length" "$image" "$dir/root" || return 1
	ubimkvol "/dev/$ubi" -N openwrt-new-data -s 8MiB || return 1
	if [ -n "$UPGRADE_BACKUP" ]; then
		volume="$(nand_find_volume "$ubi" openwrt-new-data)"
		mkdir -p /tmp/grx500-new-data || return 1
		mount -t ubifs "/dev/$volume" /tmp/grx500-new-data || return 1
		if ! cp "$UPGRADE_BACKUP" "/tmp/grx500-new-data/$BACKUP_FILE"; then
			umount /tmp/grx500-new-data
			return 1
		fi
		umount /tmp/grx500-new-data || return 1
	fi
	set -- "/dev/$ubi" "kernel$bank" openwrt-backup-kernel \
		openwrt-new-kernel "kernel$bank" "rootfs$bank" openwrt-backup-rootfs \
		openwrt-new-rootfs "rootfs$bank"
	volume="$(nand_find_volume "$ubi" rootfs_data)"
	[ -z "$volume" ] || set -- "$@" rootfs_data openwrt-backup-data
	set -- "$@" openwrt-new-data rootfs_data
	for name in "kernel$bank" "rootfs$bank" rootfs_data; do
		volume="$(nand_find_volume "$ubi" "$name")"
		[ -z "$volume" ] || nand_remove_ubiblock "$volume" || return 1
	done
	# A single UBI rename ioctl switches kernel, rootfs and overlay together.
	# Stock U-Boot keeps using the same names; environment/bootcore stay intact.
	ubirename "$@" || return 1
	sync
}

platform_do_upgrade() {
	grx500_upgrade_tar "$1" || {
		echo "AX3000 upgrade failed before commit; existing active volumes retained."
		return 1
	}
}
