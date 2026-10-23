DFS callback drain before Wi-Fi unregister
=========================================

This report describes an earlier image. The newer unapproved container and
the station callback drain are in ``mac-callback-quiesce-audit.rst``.

``package/kernel/iwlwav-stock/patches/240-dfs-workqueue-quiesce.patch``
closes the master's DFS-event workqueue before ``ieee80211_unregister_hw``.
The old cleanup flushed that queue only when the DF user was destroyed, after
mac80211 unregister. Its worker calls cfg80211 with the associated wiphy. A
late worker could therefore enter cfg80211 while the wiphy was being removed.

The patch closes event admission under a spinlock, waits for queued or running
work, and frees events that were added but never scheduled. Producers check
the gate when adding or scheduling. The existing DF cleanup calls the same
quiesce path before destroying the workqueue. ``wave_radio_scan_quiesce``
invokes it while both wiphys and the master DF still exist. The current MMB
cleanup order calls that function before mac80211 unregister.

``package/kernel/iwlwav-stock/tests/dfs-workqueue-quiesce.py`` extracts the
actual patched producer, worker, quiesce and cleanup functions into a pthread
fixture. Native AddressSanitizer/UndefinedBehaviorSanitizer and static MIPS
execution under QEMU both pass normal delivery, an unscheduled-event purge,
post-close rejection, a blocked in-flight cfg80211 callback, and 1000 racing
producer attempts. The separate teardown-order fixture passes 556 cases on
native and MIPS. The package and both complete image variants rebuild.

The module extracted from each final sysupgrade rootfs has SHA-256
``6a6f9f917d531232c1c017d9c38dd6fa6bc66f951a6519403f508f85f2bab2b5``
and contains ``mtlk_df_user_quiesce_prop_dfs_wq``. The development initramfs
audit passes. The factory image passes exact ELF, rootfs, metadata, partition
permission and first-boot checks, and its 347 relevant build inputs match the
development source apart from the explicit factory trial setting. Both builds
use their normalized ``make defconfig`` configurations and rebuilt kernel
module packages. That stage's
unapproved factory container has SHA-256
``9dc9d6704b7c674ad5ed041d7f5790bebae172293f49ef61be4412acf337efa0``.
Its exact bytes pass the pinned stock checker and a stock-writer capture
test under QEMU, with flash commands intercepted. The pinned stock LuCI
multipart route preserves those bytes and dispatches checker before writer.
Stock uhttpd preserves the exact 9,040,538-byte multipart request in both
tested HTTP request modes. The retained bindings are in
``dfs-workqueue-quiesce-results.json``.
Those development and factory loaders also pass their compiled
four-argument Linux handoff checks. The latest REA bootloader output and
both corresponding loader reports pass the bound boot-argument layout check with
three rejected instruction mutations.

The fixture is a model of selected synchronization and does not run the
kernel or radios. It cannot prove that other driver recovery paths are safe.
REA's bootloader evidence is for the official AX3000(US) V1 firmware, not
the user's v1.6 unit. No NAND write, boot, bank fallback, Ethernet packet
transfer, Wi-Fi association, 160 MHz, WPA3/PMF or USB test has occurred on
that device. The candidate is not approved for stock-web upload.
