Archer AX3000 stock-ABI WAVE600 port
==================================

This package ports the exact Intel WAVE 6.0.8.0.87.0.7 d24084bd3447 source
identified in the stock AX3000 firmware to the native Linux 6.18 wireless APIs.
The driver and its RF library are extracted from the published TP-Link GPL
bundle, with SHA-256 verification of both nested archives. No proprietary
kernel module is loaded or executed during the build.

The module uses the matched stock radio firmware from ax3000-stock-firmware.
Calibration remains device-specific: the board preinit helper must supply the
actual cal_wlan*.bin files before the module is loaded. The source package does
not substitute calibration from another device. Native cfg80211/mac80211 are
built into the GRX500 kernel; OpenWrt's backports wireless modules must not be
installed alongside them.

Implemented integration
-----------------------

* Native nl80211 AP creation, beacon updates, channel/width configuration,
  scanning, station association, authorization, key installation and removal
  notifications. Native hostapd AIDs are kept separate from firmware SIDs;
  firmware SIDs are allocated and released by the driver.
* 2.4/5 GHz HT, VHT and HE capability reporting, with EEPROM-derived spatial
  stream limits and contiguous 160 MHz on supported hardware. The HE MCS maps
  advertise MCS0-11 for supported streams. Native AP startup explicitly
  enables the existing firmware HE-MU/MU scheduler commands according to
  the configured HE/VHT capabilities; it does not rely on vendor scripts.
* HE station serialization preserves the existing firmware UMI layout:
  extension ID 35 plus the 17-byte HE MAC/PHY element, eight bytes of MCS maps
  and up to thirteen bytes of PPE thresholds. Width-dependent offsets and
  lengths are validated; capabilities for unsupported 80+80 operation are
  excluded while contiguous 160 MHz remains available. The host-side old
  15-byte MAC/PHY buffer is corrected to the actual 18-byte firmware field.
* Beacon parsing locates the HE extension ID explicitly, preserves HE MCS
  maps and propagates the advertised BSS color instead of hardcoding color4.
  Partial native beacon updates merge with the prior template under the
  driver serializer.
* Native userspace SAE authentication and protected management frames, with
  firmware pairwise protection and software BIP-CMAC128/256 and
  BIP-GMAC128/256 integrity, IGTK slots 4/5, independent packet numbers,
  replay-safe key replacement and zeroization. AP receive rejects group robust
  management from stations and unprotected robust frames from MFP peers.
* Native regulatory notifications and AP startup copy the selected country
  into the firmware regulatory command. No vendor hostapd INITIAL_DATA
  command or auxiliary station PHY is required.
* Software Ethernet-style TX/RX path independent of vendor DirectConnect:
  skb linearization/checksums, mapping-error handling, bounds checks, coherent
  ring allocations and DMA ownership barriers. The interface name is not
  constrained to the stock wlan prefix.
* Native firmware recovery station notifications before station state is
  discarded; the hostapd synchronization gate reopens after restoration.
  COMPLETE recovery emits a PCI event for a bounded native netifd/module
  reload helper, preserving the existing per-device calibration files.
* CAC honors the kernel regulatory minimum; firmware-owned CSA countdown
  is followed by installation of native hostapd's final beacon template.
* Linux 6.18 timer, procfs, generic-netlink, IRQ/DMA, netdev lifetime, WEXT
  diagnostics and wireless callback adapters.

Only AP-capable PHYs are registered by default, so OpenWrt wireless detection
creates valid AP configurations. Load mtlk with sta_phy=1 to additionally
register the separate station-only mac80211 PHYs. Their contexts remain
allocated in AP-only configurations because shared driver helpers use them.

The matching firmware explicitly lacks 80+80 MHz HE operation and TWT command
support. Neither is advertised. Standalone deletion of data keys has no
identified firmware command; it returns EOPNOTSUPP rather than claiming to
remove a key. Station/VAP removal clears firmware state, replacement key
installation performs rotation, and software IGTK deletion zeroizes the key.

Evidence and verification
-------------------------

The stock source UMI_STA_ADD layout is unchanged. The native HE serialization
is corroborated by Intel's later GRX500 driver at commit
b6ae17b7580b47f1295239c8c41458c2ba8d30c6, whose core explicitly writes extension
ID35 followed by the 17-byte native HE element into the same 18-byte firmware
field. That driver's A0/B0 HE capability tables and the stock configuration
provide the capability flags; no newer driver firmware ABI is imported.

The source was cross-compiled for big-endian MIPS against the integrated
GRX500 Linux 6.18.55 kernel. Both mtlk.ko and mtlkroot.ko link and pass modpost.
The RX data path also bounds received offset+length against the DMA mapping,
independently of allocator tailroom. Run ``tests/rx-dma-bounds.py <prepared-source>``
for the extracted-branch regression; the complete RX handler and hardware DMA
are outside that test's scope. See the target's
``experimental/firmware-audit/rx-buffer-audit.rst`` for the reproduced failure.
RX allocation/cleanup and returned recovery descriptors have separate tests:
``tests/rx-ownership.py <prepared-source>`` and
``tests/rx-recovery-descriptor.py <prepared-source>``. They execute the actual
functions with mocked DMA/ring leaves; see the target's
``experimental/firmware-audit/rx-recovery-audit.rst`` for their limits.
Management TX mapping/cleanup and the normal completion ownership block are
covered by ``tests/bss-tx-ownership.py <prepared-source>``. This closes the DMA
mapping leak and now covers pending management-skb release. The separate
``tests/teardown-order.py <prepared-source>`` checks IRQ rollback and resource
release order. Complete control-worker lifetime and recovery/removal
serialization remain unverified. See the target's
``experimental/firmware-audit/wifi-teardown-audit.rst``.
Data TX now tracks mapping ownership independently of its address, releases
rejected-submission mappings, and clears packet references before descriptor
reuse. ``tests/data-tx-ownership.py <prepared-source>`` and
``tests/tx-completion.py <prepared-source>`` cover selected submission,
recovery and completion functions with modeled DMA/ring/list operations.
See ``experimental/firmware-audit/data-tx-audit.rst`` for their limits.
Recovery now drains Linux IRQ/tasklet activity and keeps normal events closed
until rings are reconstructed. ``tests/recovery-irq.py <prepared-source>``
exercises the restore function and failure/retry paths with modeled resource
and synchronization leaves. Asynchronous workers and unregister/removal
still need physical lifecycle validation; see
``experimental/firmware-audit/recovery-irq-audit.rst``.
Data and public management TX submissions now use a gate that recovery closes
and drains before ring cleanup. Permanent stop also cancels deferred reset
initiation before recovery-context teardown. ``tests/tx-producer-gate.py``
executes the actual gate and wrappers with concurrent pthread producers and
modeled workqueues. See ``experimental/firmware-audit/tx-gate-audit.rst``;
complete recovery-task, callback and VAP/core lifetime exclusion is unverified.
Asynchronous station management TX now owns its cookie and packet until
submission accepts it or request completion releases it. Optional callbacks
are checked on allocation failure; BSS completions release no-ACK packets
even with cookie zero. ``tests/async-management.py`` exercises the actual
request functions with deferred execution and failure fixtures. See
``experimental/firmware-audit/async-management-audit.rst`` for the reproduced
stack-lifetime/null-callback faults and its original removal-lifetime boundary.
A separate station-request lifetime barrier now drains queued asynchronous
TX callbacks before recovery-context cleanup and mac80211 unregister. The
extended ``tests/async-management.py`` checks concurrent close/drain behavior;
``experimental/firmware-audit/station-request-drain-audit.rst`` distinguishes
this request lifetime from still-unresolved firmware completion/RX lifetimes.
A later removal barrier now waits briefly for already accepted data/BSS frames,
closes ordinary events, drains active tasklets and returns pending management
packets before mac80211 unregister. Command confirmations remain available for
interface shutdown and firmware-owned DMA buffers remain mapped until reset.
The extended ``tests/bss-tx-ownership.py`` covers the selected release, wait
and callback gate with modeled IRQ/DMA leaves. See
``experimental/firmware-audit/mac-callback-quiesce-audit.rst`` for the exact
scope and unresolved control/scan callback paths.
``tests/bss-removed-vap.py`` executes the complete BSS confirmation handler
with modeled DMA, descriptor lists and callbacks. It reproduces the old
whole-card reset after VAP deletion and the reserve-frame metadata mixup;
patches 244 and 245 correct those paths. See
``experimental/firmware-audit/bss-removed-vap-audit.rst`` for the bound images
and its then-remaining VAP/netdev lifetime boundary. Patch 254 closes the
specifically audited station terminal-removal ownership paths below.
Patches 246-248 keep AP VAP add/delete on the RTNL-owning caller while
preserving the serializer slot, unpublish the VAP and drain hardware tasklets
before cleanup, and use cfg80211's netdev APIs when the callback also owns the
wiphy mutex. The legacy index-add path now passes its radio wiphy.
``tests/serializable-caller-rtnl.py`` and ``tests/vap-tasklet-lifetime.py``
execute the patched functions with native and MIPS thread models;
``tests/cfg80211-netdev-lock-contract.py`` checks the exact target kernel's
nl80211/cfg80211 locking contract. These tests do not establish hardware
boot, radio function or a safe stock-web upload. See
``experimental/firmware-audit/vap-rtnl-lifetime-audit.rst``.
Patch 249 also rolls back the initialized DF/netdev if TXMM/TXDM setup fails
before VAP publication. ``tests/vap-create-rollback.py`` injects that failure
into the actual create function; without the cleanup, a registered netdev
retains a pointer to a freed VAP handle. The native and MIPS tests check
rollback order and the ordinary creation/start paths.
Patch 254 gives failed station removal an owner independent of mac80211's VIF:
all VIF-table readers serialize with unpublication, the station DF holds its
own netdev reference, and a delayed worker retries recovery timeout,
unavailable-master and exhausted-delete cases. New station admission is
blocked until the old manager slot is released, and unregister cancels the
worker before final VAP-manager cleanup. ``tests/station-remove-lifetime.py``
extracts these functions and passes all terminal and ordinary cases under
ASan/UBSan. The complete development images build and pass static image,
ELF-binding and rootfs audits. This is still modeled/static evidence, not
target workqueue, recovery or RF execution; see
``experimental/firmware-audit/station-remove-terminal-audit.rst``.
Patch 255 closes an adjacent vendor-command lifetime: the unconnected-station
request no longer queues a raw ``wireless_dev`` pointer after the nl80211
callback returns. It waits on the core serializer while Linux retains the
wiphy lock, propagates request errors, and initializes the result before a
stale-interface exit can emit it. ``tests/unconnected-sta-lifetime.py`` runs
the actual submit function under ASan/UBSan, and the extended
``tests/cfg80211-netdev-lock-contract.py`` verifies the exact Linux 6.18.55
vendor-command lock sequence. This does not execute firmware channel changes
or interface teardown on hardware; see
``experimental/firmware-audit/unconnected-sta-lifetime-audit.rst``.
Patch 256 closes the remaining asynchronous channel-request teardown race.
The DFS-beacon and CAC producers copied a raw master netdev into queued
``SET_CHAN`` work; a producer that passed a plain removal check could enqueue
behind teardown's serializer barrier. A per-radio spinlock admission gate now
closes new submissions and drains producers through the clipboard copy before
that barrier is issued. ``tests/async-channel-request-gate.py`` runs the actual
gate, teardown and normal producer under native ASan/UBSan and as static MIPS,
while ``tests/scan-cancel.py`` verifies both channel producers and the existing
timer paths. This is modeled/build evidence, not real CAC, channel-switch or
unregister execution; see
``experimental/firmware-audit/async-channel-request-gate-audit.rst``.
Patch 257 removes the allocation and user-command filtering failure paths from
the removal barrier that patch 256 depends on. A stack-owned command runs local
scan cleanup at the same FIFO priority as channel work; a rejecting serializer
is drained and joined before cleanup can run on the removal thread. Serializer
stop now tolerates the later normal lifecycle cleanup. The extracted native
and MIPS fixture covers queue ordering, cancellation and rejection; see
``experimental/firmware-audit/removal-scan-barrier-audit.rst``.
Patch 258 rejects Linux error pointers returned by ``kthread_run``. Previously
worker creation failure was reported as successful serializer startup and
later stop could dereference the error pointer. The regression uses the actual
OS-dependent functions and vendor startup/rollback macros, checks all 4,095
error-pointer encodings, and retries startup on the same object after each
failure. See ``experimental/firmware-audit/serializer-thread-start-audit.rst``.
Patch 259 unpublishes the serializer's current command under its enumeration
lock before completion can free it or wake its owner. This closes the gap in
which ``serializer_dump`` could read a freed command. The regression pauses
actual core completion after freeing its context and enumerates concurrently;
see ``experimental/firmware-audit/serializer-current-lifetime-audit.rst``.
Hardware-scan cancellation now has a mac80211 callback, and module removal
drains each radio's scan on its serializer before the wiphys are destroyed.
Fatal-recovery suppression no longer blocks completion during removal; a
request that failed before starting is no longer falsely accepted. Run
``tests/scan-cancel.py <prepared-source>`` for the modeled timer/callback
cases and see ``experimental/firmware-audit/scan-cancel-audit.rst`` for the
remaining hardware and serializer-failure limits.
The scheduled-scan callback now uses the OSAL timer's return-value rearm
instead of synchronously deleting itself. Removal releases a queued CAC
handler's radar wait, cancels both control timers and suppresses late CAC
notifications. The extended ``tests/scan-cancel.py`` exercises these paths;
see ``experimental/firmware-audit/control-timer-audit.rst``.
The HE byte serializer has host tests for 80/160/80+80 maps, optional PPE,
eight-to-four NSS reduction and every truncated input length. Run them with::

  cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -I<prepared-source>/wireless/driver/linux tests/he-wire.c -o /tmp/he-wire
  /tmp/he-wire

The actual C PMF frame builder is also tested with host crypto adapters and
independent CMAC/AES-GCM expected-message checks (requires OpenSSL headers and
Python cryptography)::

  python3 tests/pmf-frame-test.py <prepared-source>

This checks MMIE layout, MIC coverage, all four BIP suites, key selection,
packet-number exhaustion, key deletion and prevention of an unprotected
fallback after key removal. It does not emulate kernel crypto scheduling,
locking or firmware unicast protection.

Build through OpenWrt after selecting kmod-iwlwav-stock::

  make package/kernel/iwlwav-stock/compile V=s

Hardware validation is still required. A successful build establishes kernel
API/symbol compatibility and the tested wire transformations; it cannot prove
PCIe link training, firmware startup, calibration acceptance, RF performance
or over-the-air interoperability on an unplugged router. The management RX
ring does not expose a decoded MIC/replay result; firmware rejection of invalid
pairwise protected frames must be verified with negative over-the-air tests.
Required tests include
both bands, HE40/HE80/HE160 as permitted by the regulatory domain, WPA2 and
SAE/PMF association, bidirectional traffic, multicast, key rotation, AP restart,
DFS/CAC/channel switching and firmware recovery.

See CAPABILITIES.rst for the stock/native feature matrix and firmware limits.
