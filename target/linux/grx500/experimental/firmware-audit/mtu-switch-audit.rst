Ethernet switch frame-length configuration
==========================================

The MTU capacity work in mtu-audit.rst did not exercise switch register
helpers: those leaves were mocked. Testing those actual helpers exposed an
additional mismatch. Requesting MTU 8000 programmed GSW-L PMAC_CTRL_3 to
9216 bytes but GSW-R PMAC_CTRL_3 to 1662. The register header describes that
14-bit field as the jumbo frame-length threshold; GSW_PMAC_GLBL_CFG_SET
programs it from nMaxJumboLen, documented as the maximum jumbo-frame length.
The vendor GPL Ethernet driver uses 1728 on GSW-R, also below the advertised
maximum. Neither value establishes full-size packet delivery through this
port. These findings are source/register-fixture evidence, not measurements
of the stock router.

Changes
-------

Both PMACs now use the existing GSW-L limit of 9216 when enabling jumbo
frames. It accommodates the advertised 8000-byte MTU with Ethernet, VLAN
and PMAC overhead and fits the configured 16 KiB CBM buffers. Existing
larger shared length settings are retained, and the unrelated high bits of
the 14-bit length registers are preserved. The shared MAC_FLEN registers
likewise only grow, so lowering one netdev's MTU does not reduce another
netdev's accepted range. MAC_FLEN retains the vendor Ethernet-header/FCS
accounting; tagged-frame processing still needs physical verification.

All register reads/writes on this MTU path now propagate switch API errors.
The old helpers ignored them; a fixture injecting failure on the first read
still observed success and MTU 8000. The new code returns -EIO and keeps
both the reported MTU and per-netdev jumbo state unchanged. Shared limits
and CPU-facing jumbo configuration are set before enabling the external
port. If a later operation fails, completed shared changes only widen the
accepted range; the change is not an atomic register transaction. Retrying
the operation is tested. Reducing the MTU clears only that external port's
jumbo bit, and a failed clear does not update the software state.

Initial GSWIP30 MTU programming now occurs before PHY/subinterface resource
acquisition, and registration fails if it cannot be programmed. The former
end-of-init call ignored the result. The actual switch RegisterGet/Set API
checks whether its device context exists but does not report every possible
MMIO/bus failure. Propagating its return values cannot establish successful
physical register writes or protection from hardware faults.

Validation
----------

test-mtu-switch.py extracts the real register and MTU helpers. Only the
switch API, device objects and unrelated MAC provider are fixtures. It
reproduces both defects against the retained before-source and passes
48,047 cases under native ASan/UBSan and big-endian MIPS userspace emulation:

* Every requested MTU from 0 through 9583 for the four configured LAN ports
  and WAN, checking bounds and programmed frame-length budgets.
* Every API-call failure during normal-to-jumbo, jumbo growth, jumbo-to-normal
  and normal-to-normal transitions, including unchanged device state and
  successful retry after the injected error is removed.
* Missing switch providers, preservation of unrelated register bits and
  larger shared settings, and simultaneous LAN/WAN jumbo configuration
  followed by lowering one LAN interface's MTU.

The separate 19,183-case capacity suite also passes with the changed helper
interface. Exact inputs, logs, full-build and image-binding results are
recorded in mtu-switch-results.json. The fixture models register storage and
API return codes; it does not model switch packet processing, DMA, traffic,
hardware write failures or concurrent firmware access.

These remain development images. Physical Ethernet and both radios, full
peripheral behavior, NAND installation and reliable serial-free recovery
remain unverified. There is no replacement stock-web factory container.
