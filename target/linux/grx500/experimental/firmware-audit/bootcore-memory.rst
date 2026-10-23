Bootcore memory and RAM boot sequence
====================================

The AX3000's 224 MiB Linux memory range, 0x20000000 through 0x2dffffff,
excludes the stock auxiliary processor's 32 MiB at 0x2e000000 through
0x2fffffff. The bootcore's apparent ``mem=32M@128M`` refers to its own
4KEc address space. Its FMT1 hardware translation prevents that range from
aliasing Linux RAM at 0x28000000.

Evidence chain
--------------

* Product ``Iplatform/build/product_configs/ax3000v1/sdk.config`` selects
  ``CONFIG_UBOOT_CONFIG_TOS_32M=y``, ``CONFIG_UBOOT_CONFIG_DDR_256M=y`` and
  ``CONFIG_UBOOT_CONFIG_FMT1_REG=0xFE002E00`` at lines 1229, 1232 and 1235.
  Its SHA-256 is
  ``525f0876824170e5a571a6f4f69c8c87e3f845bebe415014b1d39089be6094f7``.
* The same GPL archive's ``ugw/feeds_opensrc/bootloaders/open_uboot/patches/
  508-board_grx500.patch`` contains the FMT1 configuration table at lines
  1570–1583. DDR256M/TOS32M selects 0xfe002e00. Its ``fmt_init`` example
  at lines 8118–8125 documents FMT1 translating the 0x88000000/0xa8000000
  CPU window to the encoded DRAM base; its example 0xf8002800 means
  128 MiB at 0x28000000. The product value instead means 32 MiB at
  0x2e000000. The 4KEc startup writes CONFIG_FMT1_REG to 0xb49001d4
  at line 10404 before loading bootcore. Patch SHA-256:
  ``35d3dc43953bbe470d55405a0d898b13fc1f889980e8232b8c1d15939bc91a6e``.
* This is corroborated by instructions in the actual official 230831
  firmware, SHA-256
  ``96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b``.
  At absolute file offset 0x97f7, the stock SPL contains these big-endian
  MIPS instructions::

    3c03fe00  lui   v1,0xfe00
    24632e00  addiu v1,v1,0x2e00
    3c02b490  lui   v0,0xb490
    8fbc0010  lw    gp,16(sp)
    ac4301d4  sw    v1,0x1d4(v0)

  Thus the shipped code writes the product's FMT1 value, rather than the
  generic 128 MiB example. The offset is in the complete vendor image,
  not in the separately decompressed second-stage U-Boot.

Reproduce the binary check without executing firmware::

  python3 - /path/to/stock-230831.bin <<'PY'
  import hashlib, pathlib, sys
  data = pathlib.Path(sys.argv[1]).read_bytes()
  assert hashlib.sha256(data).hexdigest() == \
      '96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b'
  assert data[0x97f7:0x97f7+20] == bytes.fromhex(
      '3c03fe00 24632e00 3c02b490 8fbc0010 ac4301d4')
  print('Stock SPL programs FMT1=0xfe002e00 at 0xb49001d4')
  PY

Boot sequence implications
--------------------------

The product's ``net_ram``, ``net_flash`` and ``flash_flash`` all call
``run run_bootcore`` before loading the main Linux image. Preserve that
order for a cold RAM test. It reads bootcore into temporary 0xa0400000,
then ``secboot load_os 0x88000000 0xa0400000 0x200000`` requests the
4KEc-side copy/start through shared MPS registers. The load_os command
implementation is in GPL patch ``237-cmd-load-bootcore.patch``; it does
not change the main CPU's EVA mapping. Running it after downloading the
RAM image could overwrite part of that download.

``run_bootcore`` calls ``ubi_init``. Product ``check_image1`` and
``check_image3`` execute ``save`` while transitioning trial boot state;
states 0 and 2 select stable banks without that environment save. UBI
attachment itself can perform housekeeping writes. A RAM boot procedure
which runs these stock commands must not promise zero flash writes.
Keep all existing bootcore and factory volumes intact.

The actual on-device environment, any different installed bootloader,
bootcore volume contents and runtime startup remain unobserved. This is
static firmware evidence, not proof of successful boot on the user's unit.
