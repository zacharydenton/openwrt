Station startup and VAP-add rollback on the AX3000 WAVE port
============================================================

Patch 251 fixes three source-level failure cases in the TP-Link-matched WAVE
driver. The mac80211 ``start`` callback previously set the radio's
``sta_vifs_exist`` flag before allocating its VIF table. On allocation
failure it returned with no table but left the flag set. It also returned
WAVE's internal ``MTLK_ERR_NO_MEM`` value (-6) directly to mac80211 rather
than Linux ``-ENOMEM`` (-12).

The MBSS add handler previously created an AP or station VAP, then could fail
to push the resulting pointer into its clipboard. It purged the clipboard but
left the newly created VAP running. Patch 251 stops and deletes the VAP in
both branches before returning the allocation error. The surrounding
recovery/VAP gate from patch 250 remains held through this rollback.

``station-start-add-rollback.py`` compiles the actual prepared start and add
functions with fault-injected allocation and clipboard calls under native
ASan/UBSan and static MIPS QEMU. All six cases pass on the patched source: start allocation
failure, normal start, AP and station clipboard failure, and both normal add
paths. On the unpatched vendor source the three failure cases fail while the
normal controls pass. The OpenWrt MIPS module and development, factory and
DirectConnect images rebuild. Each rebuilt image passes its static image and
sysupgrade audit. The factory build passes first-boot prerequisites, has 358
matching build inputs with the development port, and yields an unapproved
stock-web container accepted by the pinned checker/writer harness in 16 cases
and by the stock Lua upload route harness.

Patch 254 subsequently closes the known terminal station ``remove_interface``
paths recorded in ``station-remove-terminal-audit.rst`` using independent
deferred VAP/netdev ownership. No boot, flash, Ethernet packet flow, Wi-Fi
association, or recovery was tested on hardware. The earlier factory
container predates patch 254 and remains unapproved for upload.
