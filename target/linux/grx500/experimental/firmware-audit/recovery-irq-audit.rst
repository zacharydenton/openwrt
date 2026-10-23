Wi-Fi recovery interrupt draining and event ordering
====================================================

Patch 170-recovery-irq-drain.patch closes a specific gap between interrupt
masking and rebuilding firmware rings. It does not complete synchronization
of all producers, workers, unregister or recovery/removal interactions.
Ethernet, RF traffic and installation/recovery remain untested on hardware.

Source findings
---------------

The recovery initiator masked device interrupts. Already-running IRQ handlers
and scheduled tasklets could still access old rings, and a tasklet could
re-enable a hardware interrupt source after that mask. The isolate path set
event flags but did not drain these callbacks. mtlk_hw_mmb_restore then reset
those flags at its entry, before resetting firmware or rebuilding any rings.
Later restore errors returned with whatever event/IRQ state had been reached.

The recovery worker now closes events, masks device interrupts, disables each
successfully registered Linux IRQ with disable_irq(), drains initialized
tasklets with tasklet_kill(), and masks device interrupts again. Linux IRQ
delivery remains disabled during the drain even if an active tasklet
re-enables a device source. A per-driver mask records disable ownership, so
repeated isolate/restore entry does not accumulate IRQ-disable depth.
The regular tasklet-cleanup helper shares the drain implementation while
retaining its initialization bookkeeping; recovery leaves tasklets reusable.

The restore path re-enables Linux IRQ delivery only after selecting the
initialization ISR and loading firmware, before the boot handshake. It clears
stale per-vector status before enabling each IRQ. Normal event processing
stays closed until control/data/management rings, receive buffers and TXMM/TXDM
have been reconstructed. It opens before the commands requiring firmware
replies. ISR-mode publication uses release stores and the IRQ dispatchers use
acquire loads. Every checked restore failure closes events and drains IRQs
again before returning. Removal balances any recovery-owned IRQ disable
before freeing the corresponding IRQ registration.

Memory-ordering follow-up
------------------------

Inspection of the first rebuilt module showed no CPU fence in the acquire
load used by MSI dispatch. The current target lacked CONFIG_WEAK_ORDERING;
Linux's MIPS barrier.h consequently reduced SMP barriers to compiler barriers.
The independently extracted stock kernel configuration explicitly enables
CONFIG_WEAK_ORDERING=y. The port must not assume stronger ordering than stock.

The INTEL_MIPS platform now selects WEAK_ORDERING and the target configuration
records it explicitly. This affects the whole SMP kernel, so the final build
uses a clean kernel reconstruction, not just a wireless module rebuild. The
initial module/config/disassembly are retained separately as before evidence.
The final configuration and compiled MSI acquire fence are checked by
verify-recovery-ordering.py. This proves the selected barrier implementation
and emitted instruction, not physical SMP/cache-coherency operation.

Validation
----------

recovery-irq.py executes the actual drain, recovery IRQ suspend/resume and IRQ
release helpers, event helpers and entire mtlk_hw_mmb_restore function. For
each of the two DCDP_SEPARATE_REG compile branches it runs:

* 164 IRQ lifecycle cases covering all registered-vector masks for 1/4/6
  vectors, the optional pending-tasklet hook, repeated suspend/resume, and
  removal while suspended;
* 168 restore cases covering optional datapath/logger/MIPS-control branches,
  failure at each reached checked operation, and a subsequent successful
  retry without accumulating IRQ-disable depth.

Both branches pass native ASan/UBSan and big-endian MIPS userspace emulation.
The existing 556-case teardown suite also passes after adapting its fixture
to the factored tasklet drain. The before-source restore run fails because
the old function resets firmware with events open and IRQs undrained.

The IRQ/tasklet API leaves model their synchronization contracts. They do
not execute concurrent Linux IRQs, tasklets, producer threads or firmware.
The fixture models a tasklet re-enabling its device source during draining;
it checks that Linux delivery stays disabled. Firmware/resource helpers are
fixtures, so failure coverage proves control-flow ordering rather than full
resource rollback. These tests do not validate DirectConnect operation even
though they exercise its conditional restore ordering. The actual configured
target does not use interrupt polling or the legacy interrupt recovery timer.

Relevant Linux 6.18.55 implementations are kernel/irq/manage.c (disable_irq,
enable_irq) and kernel/softirq.c (tasklet_kill). disable_irq can sleep and must
not be called while holding a resource needed by its IRQ handler. The added
calls run in the recovery worker and do not hold the driver's register lock.
If an IRQ is shared, disabling its Linux line temporarily delays other actions
on that line too; actual IRQ topology and recovery latency remain untested.

Remaining work
--------------

The subsequent tx-gate-audit.rst records explicit admission and draining for
data and public management TX producers, plus deferred reset initiation.
Asynchronous core/scan workers and independently owned accelerator producers
still require lifecycle auditing. Event flags alone do not supply that
synchronization. Recovery/removal
serialization must also be audited across the complete worker system; the
new IRQ-disable ownership mask assumes serialized lifecycle calls.

mac80211 unregister still precedes complete frame/status callback exclusion,
and AP cfg80211 notification/VAP lifetimes require the same end-to-end audit.
The earlier data/mgmt packet-ownership fixes do not prove these lifetime
requirements. Physical boot, both radios and all Ethernet ports, peripherals,
NAND power-loss behavior and serial-free reset/fallback remain unverified.
No replacement stock-web upload container is produced by this pass.
