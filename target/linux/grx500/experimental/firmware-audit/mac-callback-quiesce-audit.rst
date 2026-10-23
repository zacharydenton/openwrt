Station mac80211 callback drain
===============================

This report describes an earlier image. The newer unapproved container and
the AP status exception are in ``ap-status-gate-audit.rst``.

``package/kernel/iwlwav-stock/patches/241-mac-callback-quiesce.patch``
extends the existing mac80211 admission counter to station management RX
and TX-status callbacks. A queued management frame could previously reach
``ieee80211_rx_irqsafe`` while unregister was starting, even after the IRQ
event gate closed. Both callbacks now acquire an owner reference before
using mac80211. Quiesce closes admission and waits for accepted callbacks;
late management RX is discarded and late TX status consumes its skb without
calling mac80211. The null-HW TX-status edge also consumes its skb.

The test extracts these callback and gate functions from the patched vendor
source. Native ASan/UBSan and static MIPS execution under QEMU pass ordinary
delivery, post-close rejection, an in-flight RX drain and four racing
producers without late callbacks or skb leaks. The exact vendor module
rebuilds and the module extracted from both image root files has SHA-256
``24ad31d85daf1c68b035be7111080a817c7c3892040eafbedba6ccffae9412be``.

The development image audit and factory sysupgrade/first-boot audits pass.
The factory source matches 348 port build inputs. That stage's unapproved
laboratory factory container has SHA-256
``c691b7368c4081dfd3892ff8dd6e111ca37e800027d14fbdba491b6a83ec4007``.
Its exact bytes pass all 16 stock checker/writer capture cases and the
isolated stock LuCI route and uhttpd receive tests. Current loader reports
and latest REA bootloader Evidence pass the boot-argument layout check.
``mac-callback-quiesce-results.json`` binds these outputs and hashes.

The fixture does not run the Linux interrupt engine or radio firmware.
This patch covers the identified station callbacks, not all AP cfg80211
events or complete recovery/removal serialization. The stock tests execute
no flash commands. No boot, Ethernet, Wi-Fi, peripheral or fallback test
has run on the user's v1.6 router. This container is not approved for
stock-web upload.
