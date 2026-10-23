mac80211 station removal has independent deferred lifetime ownership
====================================================================

This audit applies to the experimental Archer AX3000(US) v1.6 port based on
OpenWrt ``bf46a5077ea14291164b145f62efcaf7d67a8f8a`` and the prepared WAVE
driver through patch 254. No router was booted.

Original failure
----------------

Linux clears ``IEEE80211_SDATA_IN_DRIVER`` before the driver's ``void``
``remove_interface`` callback and may clear or release the VIF-private area
after it returns. The old callback nevertheless returned early when recovery
did not finish within 120 seconds. It also returned after 600
``MTLK_ERR_RETRY`` deletion results. Those paths either left the VIF published
or left a live VAP whose DF still referenced mac80211's netdev without owning
a reference. Patch 253 removed an unused tasklet NDP-counter reader, but other
``vif_array`` readers and the terminal VAP lifetime still required a complete
ownership design.

Patch 254 repair
----------------

Patch ``254-station-remove-deferred-lifetime.patch`` makes callback return no
longer define the lifetime of a failed station VAP deletion:

* every ``vif_array`` lookup, publication, removal and free is serialized by
  ``vif_mutex``; removal unpublishes the VIF and clears every VIF-owned pointer
  before returning on success or failure;
* station DF creation takes its own ``dev_hold`` on the external mac80211
  netdev, and DF deletion releases it with ``dev_put``;
* recovery timeout, an unavailable master DF, and exhausted deletion retries
  transfer the VAP handle to a per-radio pending array and one-second delayed
  retry worker;
* a new station add returns ``-EBUSY`` while any deferred VAP still occupies a
  manager slot, preventing aliasing or replacement of its index;
* unregister closes and synchronously cancels the worker while serializers and
  the VAP manager are still alive; if deletion never succeeds, final VAP
  manager cleanup remains the owner that releases the DF and netdev reference.

The deferred path deletes only a station VAP. It does not register or
unregister an AP netdev from the workqueue context; station DF cleanup drops
the independently held external-netdev reference. The existing recovery/VAP
gate continues to serialize each deletion attempt with recovery snapshotting.

Verification
------------

``iwlwav-stock/tests/station-remove-lifetime.py`` extracts the actual delete,
pending-work, stop and ``remove_interface`` functions. Its native ASan/UBSan
harness passes recovery timeout, 600 exhausted retries, unavailable master,
ordinary deletion and worker-shutdown ownership cases. It checks that callback
return always leaves the VIF unpublished, that deferred VAPs retain the final
netdev reference, that a later retry releases it, and that shutdown leaves an
undeleted VAP to manager teardown.

All 26 Python driver tests pass against the same prepared tree. Four older
harnesses were updated to model definitions introduced by earlier patches;
their extracted production functions and assertions are unchanged in scope.
A clean OpenWrt package rebuild applied patches 100 through 254 and linked
``mtlk.ko`` and ``mtlkroot.ko`` for Linux 6.18.55/MIPS.

A subsequent full ``make -j4`` build produced fresh development initramfs and
sysupgrade images. ``current-image-audit.json`` passed image integrity and
kernel/loader ELF binding with no missing checks. The sysupgrade audit passed
integrity, metadata, kernel/loader ELF binding and rootfs inspection. Their
SHA-256 digests and exact audit-report digests are recorded in
``station-remove-terminal-results.json``.

Boundary
--------

This closes the two known terminal station-removal source paths and the
missing-master early return in the extracted/modelled tests. It is not a
running-kernel workqueue, firmware, PCIe, DMA, RF or router test. Development
images were rebuilt and statically audited, but no factory container was
rebuilt for patch 254. Every retained factory container predates this repair
and remains unapproved for upload. Physical boot, interface add/remove during
real recovery, module unload, association, traffic, flash write and bank
fallback are still mandatory release gates.
