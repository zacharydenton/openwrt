AP management status during removal
===================================

This report describes the previous unapproved image. The current source also
uses explicit cross-CPU event-gate accesses; see
``mac-event-gate-once-audit.rst`` for the rebuilt image and container.

``package/kernel/iwlwav-stock/patches/242-ap-status-gate.patch`` closes a
reserved-BSS completion exception. The main confirmation path already avoids
cfg80211 status when MAC events are stopped. Its failed-resubmission helper
could still call ``cfg80211_mgmt_tx_status`` for an AP VAP after that gate
closed, while teardown continued to accept command confirmations. The helper
now suppresses that notification after closure and still consumes every
queued skb.

``tests/ap-status-gate.py`` extracts the actual helper. Native ASan/UBSan and
static MIPS execution under QEMU each pass 16 AP/STA, gate, cookie and VAP
cases. The unpatched helper fails the closed-wdev negative control. The
rebuilt module extracted from both image root files has SHA-256
``916f6c81ebeda4685b7e32bf6e0d89f3601c351e4a2de4a608a067d37809b026``.

The development image and factory first-boot audits pass; 349 port build
inputs match between development and factory. The current unapproved
laboratory factory container has SHA-256
``318c6c1e9e8fc3f54fcc5eaf044198498ed4fc2e70582ff1755ddd5588099bad``.
Its exact bytes pass all 16 stock checker/writer capture cases and the
isolated stock LuCI route and uhttpd receive tests. Current loader reports
and latest REA bootloader Evidence pass the boot-argument layout check.
``ap-status-gate-results.json`` binds those outputs and hashes.

The helper fixture models selected device lifetime behavior and does not
execute Linux or firmware on the router. Other AP cfg80211 callback paths,
queued core work and complete recovery still need review. The stock tests
perform no NAND writes. No boot, Ethernet, Wi-Fi, peripheral or fallback
test has run on the user's v1.6 router. This container is not approved for
stock-web upload.
