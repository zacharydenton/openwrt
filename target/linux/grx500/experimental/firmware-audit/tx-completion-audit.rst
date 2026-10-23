Wi-Fi data transmit completion ownership
========================================

Patch ``130-tx-completion-ownership.patch`` fixes a packet/DMA leak when a
data transmit completion arrives after its virtual interface stops or becomes
unavailable. This is a source-level ownership fix, not proof of functioning
Ethernet, Wi-Fi or recovery on the AX3000.

Reproduced defect
-----------------

``_mtlk_mmb_handle_dat_cfm`` previously jumped directly to descriptor return
when its VAP readiness or handle lookup failed. Neither branch unmapped or
freed the packet. Returning the descriptor removes it from the used list,
so ``_mtlk_mmb_free_unconfirmed_tx_buffers`` cannot recover the leaked packet
later. Reusing that descriptor overwrites its packet pointer.

The test executes the actual completion handler with a mapped packet and an
unavailable VAP. Before the fix, descriptor return observes one live packet
and one live DMA mapping and fails. After the fix, these resources are
released before the descriptor goes back to the pool. Normal completions
still use the core callback; the handler clears its stale pointers afterward
so the shared cleanup path does not free the packet twice.

The existing descriptor radio/VAP identity checks now precede the readiness
and handle checks. A mismatched completion must reach the existing reset
path even when a VAP is unavailable, retaining its resources for recovery
instead of treating it as a legitimate late completion. ``BD_DBG`` is defined
unconditionally by this driver's ``mtlkinc.h`` and is enabled in the fixture.

Verification scope
------------------

``package/kernel/iwlwav-stock/tests/tx-completion.py`` extracts and compiles
the actual completion function with ASan/UBSan. All 24 cases pass:

* Normal, stopped and missing VAPs with mapped data or an unmapped keepalive
  buffer, followed by duplicate completion attempts.
* Out-of-range indexes, unused descriptors and wrong radio/VAP identities
  in each of those three availability states. Invalid completions retain
  ownership for recovery and do not return the descriptor a second time.

The DMA, VAP, core callback and pool operations are fixture implementations.
Descriptor field locations are fixture macros. The test proves the exercised
cleanup/control flow; it does not validate the firmware ABI, cache coherence,
interrupt concurrency or physical packet transmission. No Ethernet source
was changed by this patch.

The wireless package and integrated development images are rebuilt. The
image audits bind the output bytes to the kernel/loader ELFs and compare the
packaged modules with the current modules using OpenWrt's actual strip recipe.
The ordinary images retain read-only boot-environment partitions and omit
the factory-install opt-in marker. See ``tx-completion-results.json`` for
the exact evidence and artifact hashes.

No replacement factory container is released. The earlier upload candidate
remains withdrawn, and the reset coverage limitations in
``reset-recovery-audit.rst`` remain unresolved. Physical Ethernet/Wi-Fi,
full device behavior and safe serial-free installation are still required.
