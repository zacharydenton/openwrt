AX3000 switch forwarding audit
=============================

The actual stock rootfs ``lib/switch/core.sh:45`` setup_vlan function only logs
success. ``core_phy.sh`` setup_port_vlan, setup_member_vlan and clear_vlan_table
also return without programming hardware. setup_switch adds a static router MAC
entry at CPU port0; the optional flow-control helper is not called. Stock
``etc/init.d/multicast`` can install hardware LAN replication rules when snooping
is enabled. These stock userspace services are not installed in this target.

The imported Intel kernel's ltq_gsw_pmac_init programs the PMAC ingress/egress
tables. Its original policy disabled learning only on GSW-R ports0–14 and set
GSW-R multicast/unknown-unicast port maps to CPU0. It did not establish isolation
between the four GSW-L netdevs; the WAN port15 also escaped the learning-disable
loop. The switch core's legacy initialization does not correct this policy.

The target function now checks the live PMAC configuration API results and
explicitly initializes CPU-only forwarding on both switch cores:

* Disable learning on GSW-L ports0–5 and GSW-R ports0–15. ``bLearning=1`` writes
  the hardware LNDIS bit and therefore means learning is disabled.
* Flush the MAC forwarding table, then set default multicast/broadcast and
  unknown-unicast maps (registers0x454 and0x455) to BIT(0). PortCfgSet changes
  these maps, so the final map writes occur after per-port configuration.
* Disable hardware VLAN-aware filtering. Linux handles VLAN policy, and frames
  retain their tags. PMAC L2 removal remains disabled.
* Match external ingress on GSW-L ports2–5 (rules0–3) and GSW-R port15 (rule0),
  forcing the alternative forwarding map to CPU0 and forcing no learning.
  These rules cover broadcast, multicast and known destinations as well as
  unknown unicast, independent of leftover forwarding entries.

The ingress rules do not match CPU source port0. Datapath's
gswip30/datapath_misc.c init_dma_pmac_template sets an explicit PMAC destination
map for FAST_ETH_LAN and FAST_ETH_WAN; software bridge transmission therefore
retains the selected egress port. The ingress rules leave all VLAN action fields
disabled and never request tag removal.

Allocation audit: both board switch nodes reserve512 global PCE rules. The
switch core marks that region used and starts CTP allocation after it. Dynamic
global bitmap allocation in datapath_pce.c is compiled only for GSWIP31. This
GSWIP30 target has no automatic dp_pce_rule_add callers; the available calls are
explicit diagnostic/proc operations. Normal netdev and bridge initialization
does not replace the board rules. Installing the old switch_cli multicast
service, enabling hardware offload, or adding PCE consumers would require
reconciling ownership of these indices first.

The changed netdev object compiled with the MIPS OpenWrt toolchain and Linux6.18
in an isolated kernel tree. Existing unrelated driver warnings remain. This is
static configuration and compile validation; Ethernet traffic, VLAN preservation
and port isolation still require device testing.
