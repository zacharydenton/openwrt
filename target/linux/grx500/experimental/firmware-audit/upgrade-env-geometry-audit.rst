AX3000 upgrade boot-environment geometry
========================================

``grx500_upgrade_bank`` reads the saved U-Boot state before choosing a UBI bank.
The stock layout places ``ubootconfigA`` at decimal offset 1048576 and
``ubootconfigB`` at 1310720. Each is a 262144-byte NAND partition with a
131072-byte erase block and a 2048-byte page. The tool uses a 16 KiB
environment at offset zero with two erase sectors. The upgrade script now
checks each partition's sysfs offset, size, erase size, write size and NAND
type before creating its ``fw_printenv`` config or accessing UBI. It refuses
an unknown layout rather than interpreting unrelated flash as the boot state.

The actual upgrade script passed nine native and nine packaged-MIPS BusyBox
test groups. The new geometry group corrupts each property in isolation and
checks that no environment read or UBI operation occurs. The other groups
cover bank selection, uncertain state, malformed images and staged UBI
replacement. Both complete images were rebuilt and their image audits bind
the packaged upgrade script to this source. The exact laboratory factory
container passed the stock checker and intercepted writer-parser cases.

``upgrade-env-geometry-results.json`` binds the source, images and logs. These
tests model MTD and UBI; no router NAND write, boot or rollback was observed.
The laboratory container remains unapproved for web upload.
