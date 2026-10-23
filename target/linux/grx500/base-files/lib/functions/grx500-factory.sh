#!/bin/sh
# Factory Ethernet identity: stock /data/default-mac, never a fixed flash offset.

grx500_factory_parse_mac() {
	local file="$1" size
	[ -f "$file" ] && [ ! -L "$file" ] || return 1
	size="$(wc -c < "$file")" || return 1
	[ "$size" -ge 6 ] && [ "$size" -le 512 ] || return 1
	hexdump -v -e '1/1 "%u\n"' "$file" | awk '
		{ for (i=1; i<=NF; i++) b[++n]=$i }
		function hex(c) {
			if (c>=48 && c<=57) return c-48
			if (c>=65 && c<=70) return c-55
			if (c>=97 && c<=102) return c-87
			return -1
		}
		END {
			if (n==6) { for(i=1;i<=6;i++) m[i]=b[i] }
			else {
				if(n<21 || b[1]!=77 || b[2]!=65 || b[3]!=67 || b[4]!=58) exit 1
				sep=b[7]; if(sep!=45 && sep!=58) exit 1
				for(i=1;i<=6;i++) {
					p=5+(i-1)*3; h=hex(b[p]); l=hex(b[p+1])
					if(h<0 || l<0 || (i<6 && b[p+2]!=sep)) exit 1
					m[i]=h*16+l
				}
				for(i=22;i<=n;i++) if(b[i]!=0 && b[i]!=10 && b[i]!=13) exit 1
			}
			if(m[1]%2) exit 1
			sum=0; for(i=1;i<=6;i++) sum+=m[i]; if(!sum) exit 1
			mac=sprintf("%02x:%02x:%02x:%02x:%02x:%02x",m[1],m[2],m[3],m[4],m[5],m[6])
			# This is the exact generic fallback in stock sbin/getfirm.
			if(mac=="00:0a:eb:13:7b:00") exit 1
			print mac
		}'
}

grx500_factory_wan_mac() {
	# Stock network_get_firm increments only the low 24 bits, preserving OUI.
	local mac="$1" suffix
	case "$mac" in
		??:??:??:??:??:??) ;;
		*) return 1;;
	esac
	suffix="${mac#*:*:*:}"
	suffix="${suffix%%:*}${suffix#*:}"
	suffix="${suffix%%:*}${suffix#*:}"
	case "$suffix" in *[!0-9a-fA-F]*) return 1;; esac
	suffix=$(( (0x$suffix + 1) & 0xffffff ))
	printf '%s:%02x:%02x:%02x\n' "${mac%:*:*:*}" \
		$((suffix >> 16)) $(((suffix >> 8) & 255)) $((suffix & 255))
}

grx500_factory_system_mtd() {
	local path found=""
	for path in /sys/class/mtd/mtd[0-9]*; do
		[ -f "$path/name" ] || continue
		[ "$(cat "$path/name")" = system_sw ] || continue
		[ -z "$found" ] || return 1
		[ "$(cat "$path/type")" = nand ] || return 1
		[ "$(cat "$path/offset")" = 2883584 ] || return 1
		[ "$(cat "$path/size")" = 130023424 ] || return 1
		[ "$(cat "$path/erasesize")" = 131072 ] || return 1
		[ "$(cat "$path/writesize")" = 2048 ] || return 1
		found="${path##*/mtd}"
	done
	[ -n "$found" ] || return 1
	printf '%s\n' "$found"
}

grx500_factory_attach() {
	local index path attached=""
	index="$(grx500_factory_system_mtd)" || return 1
	for path in /sys/class/ubi/ubi[0-9]*; do
		[ -f "$path/mtd_num" ] || continue
		[ "$(cat "$path/mtd_num")" = "$index" ] || continue
		[ -z "$attached" ] || return 1
		attached="${path##*/}"
	done
	if [ -z "$attached" ]; then
		# UBI attachment can write wear-leveling/repair metadata. Verify an
		# existing CRC-valid stock container first; never format/create one.
		grx500-check-ubi "/dev/mtd$index" || return 1
		ubiattach -m "$index" >/dev/null || return 1
		for path in /sys/class/ubi/ubi[0-9]*; do
			[ -f "$path/mtd_num" ] || continue
			[ "$(cat "$path/mtd_num")" = "$index" ] || continue
			attached="${path##*/}"
		done
	fi
	[ -n "$attached" ] || return 1
	printf '%s\n' "$attached"
}

grx500_factory_read_mac() {
	local ubi volume="" path mtd="" flags work mac result
	ubi="$(grx500_factory_attach)" || return 1
	for path in /sys/class/ubi/"${ubi}"_[0-9]*; do
		[ -f "$path/name" ] || continue
		[ "$(cat "$path/name")" = data ] || continue
		[ -z "$volume" ] || return 1
		volume="$path"
	done
	[ -n "$volume" ] || return 1
	for path in /sys/class/mtd/mtd[0-9]*; do
		[ -f "$path/name" ] || continue
		[ "$(cat "$path/name")" = data ] || continue
		[ -z "$mtd" ] || return 1
		[ "$(cat "$path/type")" = ubi ] || return 1
		flags="$(cat "$path/flags")" || return 1
		case "$flags" in 0x*) flags="${flags#0x}";; *) return 1;; esac
		case "$flags" in ''|*[!0-9a-fA-F]*) return 1;; esac
		[ "${#flags}" -le 8 ] || return 1
		[ "$((0x$flags & 0x400))" = 0 ] || return 1
		mtd="${path##*/}"
	done
	[ -n "$mtd" ] || return 1
	work="$(mktemp -d /tmp/grx500-factory.XXXXXX)" || return 1
	if ! mount -t jffs2 -o ro,nosuid,nodev,noexec "mtd:data" "$work"; then
		rmdir "$work"
		return 1
	fi
	mac="$(grx500_factory_parse_mac "$work/default-mac")"
	result=$?
	umount "$work" || return 1
	rmdir "$work"
	[ "$result" = 0 ] || return 1
	printf '%s\n' "$mac"
}
