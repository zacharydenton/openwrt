Stock binary reverse-engineering findings
========================================

Scope and provenance
--------------------

These are static observations and derived interpretations of files extracted
from Archer AX3000(US) V1 firmware 230831, not observations of the user's unit.
No target program was executed. The installed Ghidra 12.1.2 was used directly
with ``MIPS:BE:32:default`` after REA refused these explicit-o32 MIPS ELFs
without ABI flags records. Neither REA nor the inputs were patched to bypass
admission. Direct Ghidra output is **not REA Evidence**. Floating-point ABI
semantics, unresolved external calls and runtime behavior remain unverified.

Input SHA-256 values:

* ``usr/sbin/read_img``:
  ``99accff46b960d742ba6fe3bb69dc2710925d9d55fb9b24b688a29f846bfb409``
* ``bin/cal_cbr``:
  ``fd02ad027fb4106a178f41f69140af35d08ba3803d31a54fe914d7d7ac6912ae``
* ``usr/sbin/vol_mgmt`` (shipped shell script):
  ``7ea7ec9dd7326b346d22909d1051de517d13d38f5778144c48168021265e8208``
* ``opt/lantiq/lib/modules/3.10.104/net/mtlk.ko``:
  ``6d90ba7dfc9098240578e591225ae206d48c5dc3ef73ce24dfa7931b8bb9bbd6``

Complete decompiler output and headless logs are retained under
``/home/zach/code/archer-ax3000-bringup/rea-evidence/`` as
``read_img.direct-ghidra.*``, ``cal_cbr.direct-ghidra.*`` and
``mtlk.direct-ghidra.*`` and ``mtlk-firmware.direct-ghidra.*``. The kernel
module's addresses below are Ghidra analysis coordinates; they are not runtime
addresses. The executable addresses are ELF
virtual addresses. ``DecompileStock.java`` reproduces function selection and
decompilation in a disposable project; its header documents invocation.

Calibration extraction: answered
-------------------------------

``read_img`` main at ``0x00400a80`` requires two arguments. For ``wlanconfig``
and ``dectconfig`` it formats and executes::

    /usr/sbin/vol_mgmt read_calibration NAME OUTPUT

This path bypasses the separate U-Boot-address/raw-header path present in the
same binary. The latter must not be mistaken for the Wi-Fi calibration format.

The shipped ``vol_mgmt`` lines 494-506 resolve an MTD device **by name**
``calibration`` from ``/proc/mtd``. They run ``nanddump -q`` and extract the
member ``wlanconfig.gz`` from a gzip tar archive, then move that member to the
requested output. ``lib/wifi/tplink_intel.sh`` lines 2192-2194 subsequently
extract that inner archive into ``/tmp`` and run ``cal_cbr``. The utility
references ``cal_wlan0.bin`` and ``cal_wlan2.bin`` as the 2.4/5 GHz files.

If no MTD named ``calibration`` exists, ``read_calibration`` calls
``read_cfg_gz``. That function, lines 125-137, finds an MTD named
``wlanconfig``, validates gzip, decompresses it, and recompresses it to the
output. This is a supported alternate storage path, not evidence that this
particular board uses it. Neither path establishes a fixed NAND offset or
the user's per-device calibration contents.

``cal_cbr`` is a backup/recovery utility: answered
------------------------------------------------

It is not a format converter or a read-only diagnostic. Its main
``0x00401b50`` calls ``0x00401820``. That function ensures the two temporary
calibration files exist (otherwise it runs ``read_img`` and ``tar``), checks
backups, and reads ``/data/rftest/rftestflag``. The following bodies establish
side effects:

* ``0x00400ad4`` extracts ``/data/rftest/eeprom_backup.tar.gz``; compares MD5
  output for backed-up and temporary calibration files with ``md5_2G`` and
  ``md5_5G``; can rewrite those checksum files and call ``rftest -b``.
* ``0x00401484`` writes both checksum files and creates the backup archive
  from ``/tmp/cal_wlan0.bin`` and ``/tmp/cal_wlan2.bin``.
* ``0x00401354`` invokes
  ``upgrade /data/rftest/eeprom_backup.tar.gz wlanconfig 0 0``, extracts both
  files back into ``/tmp``, and invokes ``rftest -m``.

The upgrade command is a calibration write path. Its complete implementation
and ``rftest`` were not decompiled in this pass. This utility must not be
included in a read-only information collector.

Wi-Fi driver and firmware: partially answered
--------------------------------------------

The shipped module's version string identifies
``6.0.8.0.87.0.7.exported.d24084bd3447.bugfix/rel_6.0.8.0.87.PcieG5.PcieG6.Release``.
The vendor GPL archive contains the matching version/commit source package
``lq-wave-300-06.00.08.00.87.00.07.d24084bd3447.wls.src`` (source tar SHA-256
``c9dcd2b8a97d5cbc303303891daffbedb43acd918971175d980eca9e85212be4``).
Version correspondence and selected binary/source agreement do not establish
that every shipped byte was built from an unchanged copy of that source.

Direct module decompilation establishes:

* ``mtlk_df_fw_load_file`` at ``0x00060b80`` calls ``request_firmware``;
  retries an error ``-0x11`` up to ten attempts with 10 ms sleeps; on success
  returns the firmware buffer, size and context; on failure returns an error.
  The matching source is ``wireless/driver/linux/mtlk_df_fw.c``.
* ``_mtlk_pcieg6_ccr_read_chip_id`` at ``0x000cd9c4`` reads the lower 16 bits
  from the mapped radio register base plus ``0x220060``. Cross-objdump confirms
  the load, mask and offset at ELF ``.text+0xbd974``. Static reading does not
  reveal the value this register holds on the user's router.
* ``mtlk_eeprom_psdb_read_and_parse`` calls the EEPROM parser and PSDB parser,
  checks their return values and rolls back initialization after errors.
  ``mtlk_eeprom_read_and_parse`` at ``0x000f33e4`` checks the EEPROM signature,
  version, lengths and parsed data; it can finish with "No any valid EEPROM
  found". Presence of a file alone therefore does not establish valid radio
  calibration.
* The firmware loader recovered as ``FUN_000a21f4`` is called by
  ``mtlk_hw_mmb_start_card`` at its ``HW_LOAD_FIRMWARE`` step. It selects the
  ``ap_ram_%s_wrx_600_%s_phy.bin`` format for hardware type ``0x61``, uses
  ``real`` as the second substitution, takes the chip-name substitution from
  the CCR chip-info structure, and selects ``_dc_mode0`` for the fast-path
  host-interface image. Its indirect file-loader error returns immediately.
  These observations corroborate the source naming logic below; they do not
  establish the values read from the router.

The matching source provides these further derivations:

* ``mtlk_card_types.h`` lines 33-42 and 177-180 map PCI ``8086:09d0`` to
  Wave600, silicon chip ID ``0x0900`` to A0/``gen6`` and ``0x0910`` to
  B0/``gen6b``. The PCI table is in ``linux/mtlk_mmb_drv.c`` lines 1689-1698.
  Supported IDs do not prove the physically installed revision.
* ``shared/hw_mmb.c`` lines 3750-3785 form an ASIC upper/unified firmware name
  ``ap_ram_<chip-name>_wrx_600_real_phy.bin``. The lower CPU needs no separate
  file in that branch. Additional processor images use ``tx_sender``,
  ``rx_handler`` and ``host_interface`` names; fast path on this platform
  selects the ``_dc_mode0`` host-interface suffix.
* ``hw_mmb.c`` lines 1552-1555 and 8972 request ``cal_wlan<card-index*2>.bin``.
  The shipped ``etc/hotplug.d/firmware/firmware.agent`` serves requested files
  from ``/tmp`` through the firmware sysfs loading/data protocol. A new kernel
  must provide an equivalent firmware-loading path before radio initialization.

The shipped root filesystem contains ``ap_ram_gen6_wrx_600_real_phy.bin`` but
no corresponding ``ap_ram_gen6b_wrx_600_real_phy.bin`` in the inspected firmware
directories. Combined with the matched name-selection code, this supports an
A0-oriented stock firmware configuration. It remains an inference: binary
support tables or firmware inventory cannot establish the user's chip ID.

Port implications
-----------------

Keep the stock driver/firmware/calibration interface together when choosing a
porting baseline. A newer driver with only B0/D2 chip API dispatch does not
cover the stock A0 path. Matching filename spelling does not establish message
layout or firmware ABI compatibility across driver versions. PCIe enumeration,
register access, interrupts, DMA behavior and radio operation are still
unobserved. This analysis establishes concrete dependencies and rejects a
claim of completed Wi-Fi support for an image lacking them; it does not certify
that the current OpenWrt image can boot or transmit.
