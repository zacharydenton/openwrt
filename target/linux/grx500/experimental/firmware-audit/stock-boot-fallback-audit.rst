Stock U-Boot two-boot fallback contract
======================================

``verify-stock-boot-fallback.py`` checks the exact 343,580-byte bootloader in
the official 230831 US V1-family update, the pinned U-Boot 2010.06 GPL source,
and the stock ``ltqboot`` init script. It does **not** read the user's persistent
environment or execute U-Boot on the router.

The binary's 33-entry command table occupies offsets ``0x53b04..0x53e1b``.
Its sole ``save*`` command is ``saveenv`` at ``0x53da4``, pointing to the
function at ``0xa0413e60``. The matching GPL command parser accepts a unique
abbreviation, and its ``do_saveenv`` calls ``saveenv()``. This binds the
``save`` token in both trial defaults to the persistent-environment save path.
It is source correspondence and binary table evidence, not execution of that
function.

The exact default commands select B and save ``update_chk=0`` for an A-to-B
trial, or select A and save ``update_chk=2`` for a B-to-A trial. On the *next*
boot, those stable selectors select the previous bank. The modeled transitions
are::

  A stable (0) -> B trial (1) -> B running / saved 0 -> A on next boot
  B stable (2) -> A trial (3) -> A running / saved 2 -> B on next boot

When its dual-image branch is enabled, the stock ``ltqboot`` init script
commits a successful B boot by changing ``update_chk`` from 0 to 2, or an A
boot by changing it to 0. The
experimental OpenWrt factory rootfs does not include that stock script; it
requires an explicit bank- and boot-bound acceptance before its own
``fw_setenv`` commitment. The separate native and packaged-MIPS transaction
tests cover that OpenWrt policy.

There is a subtle persistent-state mismatch after a fallback: U-Boot selects
the old bank in RAM, but does not save the resulting ``active_bank`` value.
For example, after an uncommitted B trial, the next boot runs A while the
saved environment can still say ``active_bank=B``. Boot selection in the
checked defaults follows ``update_chk``, not the saved ``active_bank`` field.
The effect of that mismatch on every stock service is not established here.

``stock-boot-fallback-results.json`` binds the command-table offsets, 33
names, four default strings, both modeled transitions and input hashes.
The actual device may have a different persistent environment. NAND save
failure, power loss, an early hang, reset-button recovery and successful
stock-bank boot still require physical testing. This is not a no-brick proof.

Reproduce from the OpenWrt repository root::

  python3 target/linux/grx500/experimental/firmware-audit/verify-stock-boot-fallback.py \
    --bootloader /home/zach/code/archer-ax3000-bringup/stock-uboot.bin \
    --uboot-source /home/zach/code/archer-ax3000-bringup/one-shot-audit/u-boot-2010.06.tar.bz2 \
    --stock-ltqboot /home/zach/code/archer-ax3000-bringup/stock-rootfs/etc/init.d/ltqboot \
    --output target/linux/grx500/experimental/firmware-audit/stock-boot-fallback-results.json
