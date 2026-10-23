Cancel scans before Wi-Fi owner removal
=====================================

Status: source change, clean wireless package build, and native/MIPS modeled
tests. No physical AX3000 has run this port. No stock-web upload is approved.

The port registered ``hw_scan`` without ``cancel_hw_scan``. Linux 6.18
mac80211 calls the latter when an interface stops during a hardware scan and
requires the driver to report its completion. The existing vendor timer also
suppressed scan timeout work during firmware fatal recovery. Module removal
could therefore destroy a wiphy while a scan callback was still pending.

Patch ``220-scan-cancel-drain.patch`` registers a nonblocking cancel callback
which sets the vendor scan-abort flag and queues its serializer work. Before
mac80211/cfg80211 unregister, the driver marks each initialized radio as
removing, then uses the existing synchronous master-serializer command to
abort an active scan and prevent another. The removal marker makes the timer
and scan-completion paths finish an aborted scan even during fatal recovery.
New scans are rejected after the marker. A scan request that failed before
``SDF_RUNNING`` now returns its real error; the vendor recovery path had
reported such a request as accepted despite having no scan to resume or
complete. Scan cleanup still frees local request resources during removal but
does not send a channel-restore command to firmware that may have crashed.

The 12-case fixture executes the actual cancel callback, timer callback,
abort request and local cleanup with modeled timer and serializer leaves. It
checks normal and fatal conditions, removal, inactive scans, duplicate
cancellation and channel-restore suppression. Native
ASan/UBSan and big-endian MIPS userspace runs pass. The 556-case teardown
fixture executes the scan-quiesce helper and verifies it precedes mac80211
unregister under partial initialization and IRQ failures. A clean package
rebuild applies patch 220 and reconstructs the six compiled source files.
The integrated image and module checks are recorded in
``scan-cancel-results.json``.

The fixtures cannot simulate real Linux wiphy work, firmware recovery,
serializer failure, RF or the router hardware. If the control serializer
cannot process the synchronous abort, an outstanding scan may remain.
Physical boot, Ethernet, both radios, peripherals, NAND power-loss behavior
and serial-free early-hang recovery remain unverified. No new factory
container has been created.
