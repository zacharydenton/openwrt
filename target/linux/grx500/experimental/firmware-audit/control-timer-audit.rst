Drain Wi-Fi scan and CAC timers before wiphy removal
==================================================

Status: source change and modeled native/MIPS tests. Physical behavior and
stock-web installation safety remain unverified.

The vendor scheduled-scan timer callback called ``mtlk_osal_timer_set`` on
its own timer. That setter begins with a synchronous timer deletion, so a
running callback could wait on itself. The OSAL timer wrapper already rearms
when its callback returns a nonzero millisecond interval. Patch
``230-scan-control-timer-drain.patch`` uses that return path and reserves
``timer_set`` for the initial direct scheduled-scan call. It also keeps an
error code from being interpreted as an unsigned timer interval.

On radio removal, the driver now marks scans as closing, releases the radar
event that a queued CAC handler might be waiting on, and synchronously
cancels the CAC and scheduled-scan timers. The timer callbacks check the
closing marker before queueing work or rearming. The serialized CAC handler
checks the marker before and after its radar wait, so it does not report a
late CAC result or queue a channel change after teardown begins. A new
scheduled scan is rejected once removal starts.

The 21-case ``scan-cancel.py`` fixture executes the selected actual C
callbacks and cleanup functions with modeled timer, serializer and cfg80211
leaves. It verifies initial arming, wrapper-based periodic rearming,
suppression on removal, radar-wait release, a removal race during the wait,
and no late CAC notification. Native ASan/UBSan and big-endian MIPS userspace
runs pass. The 556-case teardown fixture still checks the removal ordering.
Build and image hashes are recorded in ``control-timer-results.json``.

These tests do not execute Linux timers, device firmware, the radio or the
router. The timer cancellation and serialized abort can still stall if a
different firmware/control task never completes. Physical boot, Ethernet,
both radios, full feature behavior and serial-free recovery remain unknown.
No new factory image has been made.
