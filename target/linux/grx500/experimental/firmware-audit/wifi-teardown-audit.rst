Wi-Fi pending transmit ownership and teardown order
===================================================

Patch 150-wifi-teardown-ownership.patch releases abandoned management skbs,
retains mac80211 memory until driver IRQ/tasklet draining, and unwinds partial
IRQ registration. It addresses specific source-level leaks and lifetime
ordering defects. It does not establish safe concurrent unregister/recovery
or hardware operation; the remaining synchronization gaps below still matter.

Changes and evidence
--------------------

The old _wave_radio_mac80211_deinit both unregistered and freed mac80211
state. Driver IRQs/tasklets and lower-level transmit resources were cleaned
up later. It now unregisters interfaces while firmware command replies can
still be received, retaining the owner until _wave_radio_deinit. The final
free clears radio->mac80211. The hardware getter returns NULL once this owner
has been released. Partial mac80211 registration failure similarly unregisters
immediately and retains allocated owners for the outer cleanup path.

After card finalization, _mmb_drv_cleanup now masks interrupts, unregisters
acquired IRQ handlers (free_irq synchronizes those handlers), kills initialized
tasklets, masks again in case an already-running tasklet re-enabled its source,
and resets the MAC before releasing management transmit ownership. This is
before TXMM/TXDM, radio and ring-resource destruction. IRQ/tasklet teardown
is idempotent, so the original reverse-order startup bookkeeping is retained.
Moving its cleanup macros themselves would violate the vendor's strict
step-bitmask ordering assertions.

IRQ registration now records each successful request. A subsequent failure
unregisters only those acquired IRQs; the old code returned with earlier IRQs
still registered while its initialization step was not marked complete.
Tasklet initialization is recorded separately so early/partial cleanup never
operates on uninitialized tasklets, and a second cleanup is harmless.

mtlk_hw_mmb_release_bss_tx first unmaps both management TX controllers and
then consumes their pending skbs. Normal and reserve-queue packets are
released with ieee80211_free_txskb while their mac80211 owner remains alive;
the missing-owner fallback frees the skb directly. Each descriptor's skb and
cookie are cleared, making repeated release harmless. Recovery calls this
helper after resetting the old firmware and before powering it on again.
No successful transmit status is synthesized for abandoned frames. Backing
buffers stay allocated until their existing buffer-cleanup stage.

Validation scope
----------------

* teardown-order.py executes the actual IRQ acquire/release, tasklet
  initialization/draining, early quiescence, radio unregister/free and outer
  cleanup functions against modeled kernel/resource leaves. Its 556 cases
  cover all required-IRQ masks for 1/4/6-vector configurations, every request
  failure position, repeated cleanup, each initialized-step prefix and a
  modeled partial mac80211-registration failure. The cleanup-step fixture
  checks the same reverse-order bitmask invariant as mtlkstartup.h.
* The extended bss-tx-ownership.py passes 37 cases, including both TX queues,
  both radio IDs, empty/partial pools, owner lookup failure, exactly-once
  packet consumption and repeated recovery release. It executes the actual
  release helpers and the release portion of the recovery STOP phase.
* Both suites pass native ASan/UBSan and big-endian MIPS userspace emulation.
  Before-source runs reproduce premature mac80211 free, an IRQ left registered
  after a failed second request, and two management packets left behind after
  recovery's former unmap-only cleanup.

These tests model the synchronization effects of free_irq/tasklet_kill; they
do not run a concurrent Linux interrupt engine or the complete driver worker
system. Other startup/cleanup actions are fixtures. The missing-owner fallback
does not prove that all real owner-lifetime paths are valid. Clean module/full
build and image-binding evidence is recorded in wifi-teardown-results.json.

Still required
--------------

The mac80211 unregister phase still overlaps active driver processing. Linux
6.18 ieee80211_unregister_hw explicitly expects the driver to have stopped
delivering frames before its tasklets/interfaces are removed. Delaying the
final memory free fixes one lifetime problem but does not satisfy that broader
callback-exclusion contract. Asynchronous core work and all direct
mac80211/cfg80211 callback paths need to be accounted for before claiming
unregister safety.

Recovery's mac_events_stopped flags are not themselves a synchronization
barrier for already-running callbacks or transmit producers. Its restore
entry currently resets those flags before rebuilding the old rings. The
pending-packet release helper assumes those users have been quiesced; this
assumption still needs a concrete synchronization implementation and tests.
Follow-up: ``recovery-irq-audit.rst`` records IRQ/tasklet draining and defers
normal event reopening until reconstruction; other producers/workers and
unregister/removal synchronization remain incomplete.

Follow-up: ``data-tx-audit.rst`` records the later correction of data TX's
post-mapping descriptor-error cleanup and address-zero ownership. The result
JSON for this teardown pass retains its historical outstanding-work list.
Physical boot, Ethernet, both radios, peripherals/persistence, NAND writes
and reliable serial-free installation/recovery remain unverified. The images
remain development artifacts and the stock-web factory candidate is withdrawn.
