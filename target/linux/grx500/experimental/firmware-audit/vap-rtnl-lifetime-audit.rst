AP VAP registration and deletion still cross the RTNL boundary
==============================================================

The earlier WAVE600 port must not be treated as safe for a one-shot upload.
The dynamic AP VAP path had two related source-level defects that the existing
build, QEMU upload and BSS completion tests could not exercise.

``wext_ioctl_dispatch`` in Linux 6.18.55 holds RTNL while it calls a wireless
private ioctl handler. ``PRM_ID_VAP_ADD`` and ``PRM_ID_VAP_DEL`` in
``mtlk_df_user.c`` synchronously wait for MBSS core requests. Those requests
are marked ``SERIALIZABLE`` in ``core.c``; the serializer queues them to its
own kthread. The add request reaches ``_mtlk_df_user_reg_netdev`` and calls
``register_netdevice`` on that kthread with no RTNL acquisition. The delete
request reaches ``_mtlk_df_user_unreg_netdev``. Its ``rtnl_trylock`` may fail
because the waiting ioctl thread owns RTNL; it then calls
``unregister_netdevice`` anyway. Linux's
``unregister_netdevice_queue`` asserts that the *calling thread* holds RTNL.
The same MBSS requests are also used by virtual-interface add/delete paths.
Linux 6.18.55 marks ``NL80211_CMD_NEW_INTERFACE`` and
``NL80211_CMD_DEL_INTERFACE`` with ``NL80211_FLAG_NEED_RTNL``, so the normal
nl80211 AP interface path has the same caller/kthread ownership mismatch.

The lifetime ordering is separately unsafe. ``mtlk_vap_stop`` stops the DF,
which unregisters the AP netdev, before it stops the core serializer.
``mtlk_vap_delete`` cleans up the core and DF while the VAP remains published
in ``guest_vap_array``; only afterwards does it free and clear that slot.
The hardware tasklets use that array to find a VAP for RX, TX completion,
mailbox and BSS events. A callback that has already fetched the pointer is
not pinned through cleanup. Patch 244 handles a *missing* VAP on one BSS
completion path; it cannot make an already acquired pointer safe.

This was a release blocker. A correct change needs to keep register and
unregister in an RTNL-owning context, preserve serialized firmware state
changes, and unpublish and drain VAP callbacks before freeing their core,
DF or netdev. Simply replacing ``rtnl_trylock`` with ``rtnl_lock`` would
deadlock against the waiting ioctl thread. Merely clearing the array slot
does not protect callbacks that fetched the old pointer.

Source-level mitigation after this audit
----------------------------------------

Patches 246-248 hand MBSS add/delete requests to their synchronous caller
while retaining the serializer queue position, unpublish a VAP before its
cleanup and drain already-running hardware tasklets. Linux 6.18's nl80211
add/delete callbacks also hold the wiphy mutex. The driver now selects
``cfg80211_register_netdevice``/``cfg80211_unregister_netdevice`` during
those callbacks, which avoids recursive locking by the cfg80211 netdev
notifier. Its ordinary WEXT and master-device paths retain the standard
netdevice API. The legacy index-add path now passes the radio's wiphy instead
of NULL.

Patch 249 closes an additional creation rollback hole: if TXMM/TXDM setup
failed after ``_mtlk_vap_init`` registered the AP netdev, the manager freed
the VAP handle without cleaning up that netdev. The injected failure in
``vap-create-rollback.py`` reproduced the dangling lifetime and now verifies
cleanup before free, including on MIPS QEMU.

Recovery/VAP lifetime gate
--------------------------

The hardware reset worker starts recovery outside the VAP serializers. It
snapshots published VAP handles and queues a recovery command on each VAP's
serializer. A caller-thread MBSS delete can hold the master serializer slot
while stopping a slave VAP. If recovery snapshots that slave during deletion,
the slave's recovery command can block awaiting the master recovery command;
VAP stop waits for the slave serializer, while the master command remains
behind the delete slot. That interleaving can deadlock. The tasklet drain in
patch 247 does not cover queued recovery commands.

Patch 250 adds a per-card mutex around recovery type selection, VAP snapshot
and recovery-task scheduling, and around each of the four MBSS add/delete
handlers. A mutation that enters first finishes before recovery snapshots;
when recovery enters first, a mutation returns ``MTLK_ERR_RETRY`` while the
recovery type or MAC-fatal pending flag is active. The handler's caller owns
RTNL, so this mutex does not transfer netdev operations back to a serializer
kthread. ``recovery-vap-lifetime.py`` extracts the actual admission functions
from the prepared driver and forces both interleavings under native ASan/UBSan
and MIPS QEMU. The MIPS modules and the three full image variants build. This
is source-level evidence only: real recovery, interface removal and netdev
locking remain untested on the router. The exact rebuilt images and stock
container are bound in ``recovery-vap-lifetime-fix-results.json``.

The mac80211 station ``remove_interface`` callback returns ``void``. The
original recovery-timeout and exhausted-delete paths returned with a live VAP
whose lifetime was still tied to VIF/netdev state that mac80211 could discard.
Patch 254 subsequently unpublishes and detaches the VIF, gives the VAP/DF an
independent netdev reference, retries deletion with a cancellable worker and
blocks replacement admission. ``station-remove-terminal-audit.rst`` records
the extracted ASan/UBSan cases and shutdown ownership. This closes the known
source paths but does not constitute a real recovery or module-unload test.

The rebuilt MIPS modules link, and ``serializable-caller-rtnl.py`` and
``vap-tasklet-lifetime.py`` execute the patched functions natively and under
MIPS QEMU. ``cfg80211-netdev-lock-contract.py`` checks the driver's selected
APIs against the exact Linux 6.18.55 nl80211/cfg80211 source.
``vap-rtnl-lifetime-fix-results.json`` pins patches 246-249, prepared driver
source, the replacement factory candidate and exact-image audit reports. These are
source and modeled-thread checks. They cannot demonstrate an actual AP
creation/deletion, IRQ overlap, RF operation or safe stock-web installation.
In particular, the factory kernel has no enabled hardware watchdog, so an
early kernel hang cannot be assumed to trigger stock-bank fallback.

``vap-rtnl-lifetime-results.json`` pins the original failing source and kernel
file digests. No router was booted for either audit; no Ethernet or wireless
runtime behavior is established. The laboratory factory container remains
unapproved for upload.
