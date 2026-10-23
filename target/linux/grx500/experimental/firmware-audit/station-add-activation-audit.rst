Station VAP add ownership after MAC and activation failures
===========================================================

mac80211 calls the WAVE ``add_interface`` callback and marks the VIF as in the
driver only if it returns zero. It does not call ``remove_interface`` after a
failed add. The vendor-matched callback created and published a station VAP
before writing its MAC address and activating the firmware. It ignored a
failed MAC-address write. An activation failure returned an error without
deleting the VAP, so mac80211 could discard the VIF while the driver still
held its netdev pointer. The activation helper also converted a WAVE error
to Linux errno before the add callback converted it again: WAVE no-memory
(-6) became Linux ``-ENOMEM`` (-12), then matched WAVE no-resources (-12)
and emerged as ``-EFAULT`` (-14).

Patch 252 keeps internal WAVE error codes until the add callback returns. It
checks the MAC-address write and attempts a serialized MBSS VAP deletion on
either setup error. A successful deletion restores mac80211 netdev operations,
clears the VIF slot and returns the translated setup error. If deletion itself
cannot finish within the existing retry budget, the callback returns success
while retaining the VIF and driver netdev operations. This preserves
mac80211's ownership contract so a later remove callback can retry; the
station is not claimed to be usable in this failure state.

``station-add-activation.py`` compiles the actual add, MAC, activation and
errno-translation functions with injected firmware results. Native
ASan/UBSan and static MIPS QEMU pass four cases: ordinary add, activation
failure with successful rollback, MAC write failure with successful rollback,
and exhausted rollback retries with retained VIF ownership. The same test
fails the three error cases on the vendor source. The new MIPS module and
development, factory and DirectConnect images compile. All three image and
sysupgrade audits pass. The factory build has 359 matching inputs, passes its
first-boot prerequisite audit, and yields a laboratory stock-web container
accepted by 16 pinned checker/writer cases and the stock Lua route harness.

Patch 254 subsequently closes the known terminal ``remove_interface`` paths
recorded in ``station-remove-terminal-audit.rst`` by detaching the VIF and
giving a failed VAP deletion independent deferred ownership. No boot, Ethernet
packet flow, Wi-Fi association, flash write or bank fallback was tested on the
router. The older factory container does not include patch 254 and remains
unapproved for upload.
