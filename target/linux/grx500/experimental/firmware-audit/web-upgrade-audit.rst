Stock web upgrade and MIPS runtime verification
==============================================

Verdict: none of the four produced OpenWrt images is a stock-web-upload image.
The exact stock ``nvrammanager -c`` program rejects every one. A sysupgrade
archive is for an already-running OpenWrt system; the initramfs uImage is for
RAM loading through the bootloader. Renaming either does not change its format.

Observed stock-checker execution
--------------------------------

The inspected stock release is AX3000(US) 1.0.6 Build 20230831 rel.67466.
Its checker SHA256 is
``10eb5517fa1556bc5c6b716044b7b2b9c747bf9fe7a6f792d550bf22d771c342``.
The original firmware SHA256 is
``96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b``.
The checker ran through QEMU MIPS user-mode emulation with the exact stock
libraries and default product-info. Bubblewrap provided private PID/network
namespaces, a temporary root, read-only firmware directories and no MTD/UBI
devices. Only disposable candidate files were writable. This checker suite
does not run ``-u``; the later isolated parser-capture experiment is documented
separately in ``serial-free-audit.rst``.

All 12 expectations passed:

* Unmodified official firmware: accepted, including authentication and model
  checks. This positive control establishes that the emulated checker works.
* Payload corruption, signature corruption, invalid declared length and
  truncation: rejected.
* Official firmware with mismatched model or region product-info fixtures:
  rejected. These fixtures do not represent a readout from the user's router.
* Baseline and DirectConnect initramfs and sysupgrade images: all rejected
  with ``The file's length is bad`` before authentication or hardware matching.
* Official firmware with appended trailing bytes: accepted. The checker uses
  its declared container length; it is not a complete byte-for-byte validator.

Rejected candidate files are deleted by the stock checker. The harness uses
temporary copies and verifies that accepted copies remain byte-identical.
Recorded system-call traces show no attempted MTD/UBI access. The HTTP/Lua
upload handler, actual device configuration and other firmware releases were
not executed or verified.

Why an upload wrapper alone is insufficient
-------------------------------------------

Existing direct Ghidra analysis and stock scripts establish separate paths:

* Stock ``/sbin/sysupgrade`` calls ``nvrammanager -c`` before upgrading.
  The web controller's separate ``luci.model.fmup.upd_fm`` path invokes
  ``nvrammanager -c`` and, on zero status, ``nvrammanager -u`` directly;
  see the later bytecode audit in ``serial-free-audit.rst``.
* ``FUN_0040830c`` checks the big-endian length, firmware type, authentication
  and metadata at offset 0x1014. ``FUN_00407ff0`` verifies the Cloud signature;
  ``FUN_00403104`` checks support-list and version information.
* The destructive path ``FUN_00403308`` / ``FUN_0040d2e0`` parses vendor uImage
  components and invokes ``vol_mgmt upgrade_dualvol_stdin``.
* The shipped ``vol_mgmt`` writes the opposite bank and changes ``active_bank``
  and ``update_chk`` to trial state 1 or 3 after a kernel/bootcore write. It does
  not execute this port's OpenWrt ``platform.sh`` staging/atomic-rename logic.

No supported factory-image recipe or verified migration through that stock
writer has been implemented. A later laboratory legacy-envelope experiment
passes the checker and captures the writer's kernel output; see
``serial-free-audit.rst`` and ``one-shot-audit.rst`` for the expanded tests,
resolved teardown issue and remaining installation blockers.
Passing a header/signature check would not prove bootcore,
overlay, volume capacity, bootloader handoff or recovery compatibility.

Additional MIPS userspace execution
-----------------------------------

Both actual sysupgrade root filesystems were extracted for runtime probes.
52 checks passed (26 per variant):

* Packaged hostapd, iw, jshn and fw_printenv load with their actual MIPS dynamic
  linker/libraries and answer version/help/JSON probes.
* The real HE serializer, cross-compiled for big-endian MIPS, passes its
  80/160/80+80 map, NSS, PPE and bounds cases.
* The installed factory-MAC helper runs with the packaged MIPS BusyBox shell,
  awk, hexdump and wc: 12 valid/malformed identity cases and three WAN increment,
  carry and OUI-preservation cases pass.
* The actual UBI guard C code, cross-compiled with its fixture-only file backend,
  accepts a valid synthetic table and rejects blank, corrupt and incomplete
  tables. The installed production guard rejects regular files.

These are real userspace/serializer executions, not a GRX500 machine emulator.
No kernel boot, radio association, Ethernet packet transfer or NAND-controller
operation occurred. See https://www.qemu.org/docs/master/user/main.html for
the distinction between user-mode emulation and system emulation.

Reproduction
------------

``test-stock-web-checker.py`` accepts ``--rootfs``, ``--stock``, ``--qemu``,
``--artifacts`` and ``--output``. It pins the researched firmware/checker hashes.
``test-mips-userspace.py`` accepts ``--openwrt``, ``--artifacts``, ``--qemu`` and
``--output``. Both require bubblewrap and a static qemu-mips executable; neither
falls back to running firmware outside isolation. The latter also needs the
prepared Wi-Fi source, OpenWrt cross compiler and host unsquashfs tool.

``web-checker-results.json`` and ``mips-userspace-results.json`` retain input,
tool and output hashes plus all case outcomes. Full stdout/system-call traces
and the QEMU package provenance are in the bringup ``web-upgrade-audit`` directory.
The QEMU binary was extracted from Arch's package without a system installation;
its archive digest was checked against the local pacman repository database.

The documented UART/U-Boot RAM test still requires confirmation on v1.6.
For a device without serial access, ``serial-free-audit.rst`` records the
prospective factory-container route and outstanding installation/recovery work.
Neither path has been verified on hardware.
