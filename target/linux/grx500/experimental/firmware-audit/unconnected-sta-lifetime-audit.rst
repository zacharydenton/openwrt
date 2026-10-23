Unconnected-station measurement outlived its cfg80211 interface
================================================================

The stock WAVE600 vendor command for measuring an unconnected station copied
the callback's raw ``struct wireless_dev *`` into a serialized request and
submitted that request with ``_mtlk_df_user_invoke_core_async``.  The nl80211
vendor callback then returned while the core serializer could still be
waiting, changing channel, sleeping for the configured measurement interval,
or emitting the result event through that pointer.

Linux 6.18.55 protects the object only for the callback.  Its
``NL80211_CMD_VENDOR`` operation has ``NL80211_FLAG_NEED_WIPHY`` and not
``NL80211_FLAG_NO_WIPHY_MTX``.  ``nl80211_pre_doit`` locks the wiphy,
``nl80211_vendor_cmd`` calls the driver's ``doit``, and
``nl80211_post_doit`` unlocks it.  RTNL is released before ``doit`` because
the vendor operation does not request ``NL80211_FLAG_NEED_RTNL``.  Returning
from the callback therefore discarded the only relevant cfg80211 lifetime
barrier while the asynchronous request still retained ``wdev``.

That became a concrete teardown hazard after station removal gained a
deferred terminal path.  Interface removal can unpublish and detach the VIF
while an earlier measurement remains queued.  The later core handler calls
``mtlk_df_user_from_wdev``, reads ``wdev->wiphy`` and finally passes ``wdev``
to ``wv_cfg80211_handle_get_unconnected_sta``.  Depending on timing, this was
a stale interface lookup or a use-after-free.

The first stale-interface exit had a second defect.  The handler jumped to
its event path before initializing ``vendor_unconnected_sta_res_data``.  It
could therefore copy kernel-stack bytes into a vendor event.  The command is
admin-only, but that does not make uninitialized kernel data or an invalid
pointer safe.

Source-level correction
-----------------------

Patch 255 changes only this request to synchronous serialized execution.
``wave_radio_unconnected_sta_get`` now calls ``_mtlk_df_user_invoke_core``
and consumes its clipboard with ``_mtlk_df_user_process_core_retval_void``.
The nl80211 callback consequently remains active, with the target wiphy
locked, until the serializer has consumed ``wdev`` and emitted the result
event.  Since nl80211 released RTNL before the callback, waiting for the
serializer does not transfer or recursively acquire RTNL.  Invocation and
handler errors are also returned instead of being hidden by a void async
submission.

The result structure is now zeroed immediately after the clipboard request is
decoded, before the first interface lookup.  Its address is copied and every
RSSI element receives ``MIN_RSSI`` at the same point, so every later error
event has deterministic contents.  The normal event ABI is unchanged; the
event is simply completed before the command callback returns.

This deliberately makes the vendor command wait for the configured
unconnected-station scan interval.  That bounded command latency is the cost
of retaining the cfg80211 owner.  Moving the work back to an untracked async
request would reopen the lifetime bug.

Verification
------------

``tests/unconnected-sta-lifetime.py`` parses the prepared production
``wave_radio_unconnected_sta_get`` and
``_mtlk_core_get_unconnected_station`` functions.  It rejects an async
submission, requires invoke/process/return ordering, and requires the result
initialization to precede the first ``wdev`` lookup.  It then compiles the
actual submit function with ``-Wall -Wextra -Werror`` and ASan/UBSan.  The
ordinary request, invocation failure, Gen6 rejection, wrong length, null
data, and broadcast address cases pass.

``tests/cfg80211-netdev-lock-contract.py`` now additionally parses the exact
prepared Linux 6.18.55 source.  It verifies the vendor operation's wiphy flag,
absence of the no-mutex flag, wiphy lock/unlock around ``doit``, and RTNL
release before the callback.  All 27 Python driver tests and the standalone
HE packing test pass.  All 15 zero-argument GRX500 tests pass, covering
252,192 enumerated cases, and the packaged-MIPS checksum test accepts the
intact sysupgrade while rejecting corrupted kernel and rootfs members.

The clean Wi-Fi package, integrated Linux target and full development image
builds pass for big-endian MIPS.  The rebuilt initramfs and sysupgrade images
pass their image/ELF/rootfs audits.  Exact source, object, module, package,
image and report hashes are recorded in
``unconnected-sta-lifetime-results.json``.

Hardware boundary
-----------------

No Archer AX3000 was available.  The tests do not execute firmware channel
switching, serializer contention, interface removal during a real recovery,
vendor-event delivery, module unload, RF operation, or a physical boot.  The
extra synchronous latency must be measured on the router.  No factory
container was rebuilt with patch 255, and no retained stock-web candidate is
approved for upload.
