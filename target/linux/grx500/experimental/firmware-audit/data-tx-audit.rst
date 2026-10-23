Data TX DMA ownership and rejected submission
=============================================

Patch 160-data-tx-dma-ownership.patch fixes streaming-DMA ownership in the
software data-transmit path. It does not establish working radios, concurrent
recovery safety or safe installation. The exact inputs, build/image checks
and test logs are recorded in data-tx-results.json.

Source findings and changes
---------------------------

_mtlk_hw_send_data maps a nonempty packet before its BD_DBG descriptor index
and reuse checks. Both checks formerly returned an error without unmapping
the packet or ending the CPU statistics interval. The caller
__mtlk_core_prepare_and_xmit then returned the descriptor to the free pool;
the upper transmit path remained responsible for disposing of the skb.
Neither returning the descriptor nor freeing the skb releases its mapping.

Those rejection paths now end the statistics interval and unmap before
requesting firmware reset and returning failure. They publish no descriptor
to the firmware ring. The pre-existing used bit on the reuse-error branch
is left unchanged. Mapping failure still returns before any ring operation.

Data TX completion and unconfirmed-buffer cleanup also previously tested
dma_addr != 0 as their mapping-ownership predicate. Zero can be a valid DMA
address. A new host-mirror dma_mapped flag now records successful mapping,
including address zero. Mapping failure and zero-length packets leave it
clear. The common wave_data_tx_unmap helper consumes the ownership once and
clears the stored address. Normal/stopped/missing-VAP completion, rejection
and unconfirmed-buffer cleanup all use it. This changes host bookkeeping,
not the HOST_DSC firmware layout.

Unconfirmed-buffer cleanup clears each consumed skb reference. Returning an
unsent descriptor also clears its borrowed skb reference without freeing the
caller-owned packet. The general recovery/producer exclusion problem remains:
these bookkeeping operations are not a new synchronization mechanism.

Tests and limits
----------------

data-tx-ownership.py executes the actual submission, unmap, unsent-release
and unconfirmed-cleanup functions with the actual host mirror declaration
and vendor bitfield definitions. Its 170 cases cover zero/nonzero packet
length, zero/nonzero/unaligned mapping addresses, mapping failure, invalid
index, a pre-existing used bit, successful publication, repeat-safe unmap,
and empty/partial/full recovery lists. Sizes include the descriptor field's
65535 boundary; this is encoding coverage, not a supported radio MTU claim.
DMA, publication, reset and list operations are modeled leaves. The recovery
fixture supplies already-quiesced requests; it does not execute full recovery.

tx-completion.py executes the actual completion handler and common unmap
helper. Its 48 cases cover zero/nonzero mapped addresses, empty payload,
normal/stopped/missing VAP, duplicate completion, invalid index, missing used
bit and mismatched radio/VAP. Invalid completions leave ownership for modeled
recovery cleanup. Both suites pass native ASan/UBSan and big-endian MIPS
userspace emulation.

Before-source tests reproduce an unbalanced mapping after rejected TX and
packet disposal with an active address-zero mapping in both recovery and
completion. They use the current fixture mirror/setup helper where needed;
they do not run the complete old driver or stock firmware.

A forced used-bit collision tests release of this attempt's mapping. It
does not prove recovery from arbitrary descriptor-pool corruption, two live
owners of one mirror, or concurrent submissions to that same mirror. The
existing reset path remains responsible for the detected invariant failure.
The actual IRQ engine, asynchronous workers and DMA hardware are not run.
Full callback exclusion before mac80211 unregister, synchronization of
recovery with active producers, physical Ethernet/Wi-Fi/peripheral behavior,
NAND writes and reliable serial-free reset/fallback remain unverified.
No replacement stock-web factory container is produced by this pass.
