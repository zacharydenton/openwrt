Stock fallback data-volume capacity
==================================

The official 230831 rootfs does not use an OpenWrt ``rootfs_data`` UBI volume
for its primary data mount. Its ``/etc/ltqpreinit/preinit`` calls
``vol_mgmt mount_ubi_data_vol /data`` when ``do_overlay`` is present. The
extracted ``/usr/sbin/vol_mgmt`` (SHA-256
``7ea7ec9dd7326b346d22909d1051de517d13d38f5778144c48168021265e8208``)
mounts ``ubi0:data_vol`` and creates ``data_vol`` if absent. The requested
size comes from ``/mnt/data/fs``, whose exact contents are ``ubifs:20MiB``
(SHA-256 ``bccf8380c9086419fd392c50eee7a4b5d0a29ae3afdb034e329fce57675431fa``).
An older generic hook also tries the different name ``ubi_rootfs_data``; it
does not select the trial's ``rootfs_data`` by name.

Creating an 8 MiB OpenWrt trial overlay could consume the free UBI capacity
that stock needs to create its 20 MiB data volume after fallback. The trial
preflight now reserves both volumes' eraseblocks when ``data_vol`` is absent.
At the checked 126976-byte usable eraseblock size, that is 67 plus 166, or
233 available eraseblocks. When ``data_vol`` already exists, the preflight
requires 67 free eraseblocks for the trial overlay. A failed preflight does
not create a UBI volume or change the boot environment.

The real first-boot shell library was exercised with mocked UBI and
environment leaves in a private filesystem. Both native and packaged MIPS
BusyBox runs passed the existing transaction suite and the boundary cases:
66 versus 67 free eraseblocks with ``data_vol`` present, and 232 versus 233
when it is absent. These tests do not execute NAND, UBI attach, stock preinit,
or a physical fallback. A corrupt existing ``data_vol``, bad blocks and
power-loss behavior remain unverified. The factory upload hold remains.
