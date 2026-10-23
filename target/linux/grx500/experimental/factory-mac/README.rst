Factory Ethernet MAC preservation
=================================

Direct stock evidence
---------------------

The actual 230831 nvrammanager binary was decompiled in
bringup/rea-evidence/nvrammanager.direct-ghidra.c. FUN_00402868 reads named
files from /data, then /etc/partition_config. The special raw-MTD read path
applies only to radio, not default-mac. FUN_004078a8 recognizes a six-byte
raw default-mac and formats it as MAC:XX-XX-XX-XX-XX-XX; other file contents
are returned unchanged. FUN_004027a8 writes the supplied bytes to /data/name.

Actual stock /etc/init.d/boot mounts JFFS2 from mtd:data at /data. Its embedded
DTB has no physical partition named data. The kernel contains UBI gluebi,
which exports UBI volume names as MTD names. This supports the interpretation
that data is a factory-created UBI volume, but no dump of this user's volume
table is available. The implementation requires that mapping to exist at
runtime; it never invents a flash offset or creates the missing volume.
The 16MiB logical /etc/partition_config/partition-table is not a NAND layout.

Actual stock /sbin/network_get_firm returns the factory base for LAN and adds
one to the low 24bits for WAN, wrapping within those bits and preserving the
OUI. This implementation reproduces that calculation. /sbin/getfirm's shared
fallback 00:0a:eb:13:7b:00 is explicitly rejected. No MAC is bundled in images.

Implementation
--------------

lib/functions/grx500-factory.sh checks the exact system_sw MTD name, NAND
type, offset0x2c0000, size0x7c00000, page2048 and eraseblock131072. It reuses
an existing UBI attachment. For RAM boot without an attachment, the tiny
package/utils/grx500-factory helper opens the MTD O_RDONLY, skips marked bad
blocks, and validates an existing layout-volume EC header, VID header and
all128 volume-table record CRCs. A unique dynamic data volume and existing
kernelA/B plus rootfsA/B names must be present before ubiattach is allowed.
It accepts only the stock2048-byte VID and4096-byte data offsets. Blank,
corrupt, truncated, unknown-layout or missing-data containers fail closed.

Linux6.18 and ubiattach2.3.1 have no read-only attachment UAPI flag. UBI only
enters read-only mode when the underlying MTD is read-only (or for its own
error handling). Normal attachment to writable system_sw can perform UBI
wear-leveling, recovery or metadata housekeeping writes. Therefore RAM boot
with factory-MAC discovery is NOT claimed to perform zero flash writes.
The guard avoids treating an empty flash area as a new UBI container. It
never invokes ubiformat, ubimkvol, erase, update or write commands.

160-grx500-factory-data-readonly.patch restricts gluebi to the data volume and
makes its MTD view read-only, without changing writable UBI bank character
devices. Other volumes never become fake MTD devices, preventing rootfs/overlay
discovery conflicts in fstools. Notifications for untracked volumes are ignored;
renaming data away removes its MTD view, and renaming a volume to data creates
a read-only view. The
shell reader requires that read-only flag and type ubi, validates that data
exists on the system_sw UBI device, then mounts it with
ro,nosuid,nodev,noexec. It accepts a regular non-symlink default-mac file of
six raw bytes or a strict MAC: prefix with hex pairs and consistent dash or
colon separators, optionally followed by NUL/CR/LF padding (maximum512bytes).
Zero, multicast, broadcast, malformed and shared-fallback values are refused.
The filesystem is unmounted after reading. No vendor-file fallback is used.

preinit/82_grx500_factory_mac stores only the validated address in a private
RAM file. board.d/02_network sets LAN, WAN and label_macaddr defaults from it;
existing user configuration continues to take precedence. Failure logs the
missing identity and retains the driver's generated addresses rather than
claiming a factory address was recovered.

Integration and validation
--------------------------

Select DEVICE_PACKAGES grx500-factory (depends on ubi-utils), enable
CONFIG_MTD_UBI_GLUEBI=y and CONFIG_JFFS2_FS=y, and apply the exported patch.
The existing MTD_BLOCK_RO configuration is sufficient. No physical NAND/DT
partition changes are required. The helper needs enabled BusyBox hexdump,
awk, wc, mount, umount and mktemp; the current target configuration has them.

The C utility cross-compiles for big-endian MIPS with -Wall -Wextra -Werror.
The fixture-only host build is deliberately gated by GRX500_UBI_FIXTURE_TEST;
that define is absent from the package build. test-factory.py passes25 cases
under the host shell and BusyBox shell/applets: raw/text parsing, invalid
addresses, delimiter/padding validation, low24bit carry/wrap, existing UBI
layout, CRC corruption, absent factory/bank names, blank/truncated input,
a relocated layout block, and rejection of symlink input. No live NAND,
mount, actual factory file or router boot has been tested.
