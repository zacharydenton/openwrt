Wi-Fi management transmit DMA ownership
=======================================

Patch 140-bss-tx-dma-ownership.patch adds explicit streaming-DMA ownership
to the host management-transmit mirror. It closes a mapping leak when a
radio reset abandons management frames and prevents freeing their backing
buffers while the driver still records a live mapping. Full radio recovery
and teardown remain incomplete; the remaining findings below are required
follow-up work, in addition to physical device testing.

Follow-up: wifi-teardown-audit.rst covers pending-skb release, delayed
mac80211 memory release, early IRQ/tasklet draining and partial IRQ setup
rollback. The remaining-source list below records this earlier audit;
unregister-phase callback exclusion and recovery synchronization are still
unresolved after that follow-up.

Reproduced faults and changes
----------------------------

The old mtlk_mmb_free_bss_tx_buffers freed each virt_addr without unmapping
outstanding transmissions. The recovery path also returned management
descriptors to their pools without unmapping them. Unlike receive management
buffers, transmit mirrors had no explicit mapping flag. Normal completion
unmapped but left the old DMA address, so that address alone could not
distinguish an outstanding mapping from a completed one.

The new map/unmap helpers track a boolean separately from the DMA address,
including a successful mapping at address zero. A map failure leaves no
ownership; mapping an already-mapped mirror fails without overwriting its
record. Unmap clears the flag and address and is safe to call again. Buffer
cleanup unmaps the controller's mirrors before freeing their backing memory.
The recovery STOP phase unmaps both management transmit controllers after
the old firmware reset and before powering on/restarting it. This relies on
the caller's submission/completion quiescence contract, like the existing
receive and data-transmit cleanup paths; the fixture does not prove it.

Normal station-mode management/null-frame completion now clears the skb
pointer after passing ownership to mac80211. Previously the returned or
reused mirror retained the consumed pointer. This does not itself dispose
of packets whose completion never arrives.

The added flag is in a host-only mirror, whose allocation is zeroed and
sized by sizeof(struct mtlk_hw_bss_req_mirror). The firmware HOST_DSC and
SHRAM_BSS_REQ_MSG layouts are unchanged.

Verification
------------

tests/bss-tx-ownership.py compiles the actual new map/unmap helpers, bulk
unmap and buffer-free function, plus the normal-completion ownership block
extracted from _mtlk_mmb_handle_bss_cfm. It passes 26 cases under native
ASan/UBSan and big-endian MIPS userspace emulation. Coverage includes partial
buffer allocation, active and inactive mappings, address zero, mapping
failure, duplicate map rejection, repeated cleanup, remapping, and AP/STA
management, null-data and EAPOL completion branches. DMA and status callbacks
are fixtures; firmware, complete descriptor validation/queue promotion,
interrupt concurrency and RF transmission are not exercised.

Before-fix runs use current setup helpers with the actual earlier free
function or completion block. They reproduce freeing a still-mapped buffer
and retaining a consumed skb pointer, respectively. They are not executions
of an entire earlier driver. The existing 24-case data-completion suite also
passes. The wireless package is rebuilt from a clean extraction; the prepared
source is byte-exactly the retained before source plus this patch. Integrated
build and image-content results are recorded in bss-tx-results.json.

Remaining source findings
-------------------------

* Pending management skbs are still not disposed of when recovery empties
  the used lists, or when management buffers are destroyed. Their disposal
  must use the appropriate mac80211 ownership API while its state is alive.
* _mmb_drv_cleanup calls wave_radio_mac80211_deinit (which unregisters and
  frees mac80211 hardware) before stopping card events/interrupts, freeing
  management buffers and killing tasklets. This ordering needs redesign
  and failure/concurrency tests. Bulk DMA cleanup does not fix that ordering.
* Data _mtlk_hw_send_data performs descriptor bounds/reuse checks after DMA
  mapping; those error branches return without unmapping, and its caller
  returns the descriptor to the pool. This needs a submission-ownership fix.

These observations come from current source inspection; they have not yet
been reproduced through complete reset/remove flows. They prevent claiming
complete software recovery support. Hardware boot, Ethernet, both Wi-Fi
radios, peripheral/persistence behavior and safe serial-free installation
remain unverified. No stock-web factory container is released by this work.
