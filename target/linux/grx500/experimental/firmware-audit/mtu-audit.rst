Ethernet MTU and jumbo-buffer configuration
==========================================

The software MTU mismatch identified in cbm-tx-audit.rst is corrected. The
GRX500 netdev now advertises an 8,000-byte maximum, matching the vendor GPL
Ethernet driver, and the target selects the existing 16 KiB jumbo-buffer mode
to accommodate that packet size plus DMA and protocol overhead. This is an
experimental configuration change; physical jumbo traffic is not verified.

Follow-up: mtu-switch-audit.rst covers a further PMAC frame-length mismatch
and ignored switch API errors found by replacing the mocked register helpers
with their actual implementation. The results below describe this earlier
capacity-focused build.

Evidence and implementation
---------------------------

The vendor's linux-3.10.104-sources driver defines LTQ_ETH_DATA_LEN as 8000.
The port inherited 9582 from a newer generic driver. Its GSWIP30 MTU query
returned success without writing its output: the before-fix fixture observes
the unchanged 0xfeedbeef sentinel. Linux 6.18 ether_setup also initializes
netdev max_mtu to 1500, and the port had not replaced that value. Linux would
therefore reject jumbo MTU requests before calling the driver's handler.

The new CBM capacity callback supplies packet-buffer capacity after the
configured DMA headroom. The GSWIP30 datapath then reserves the maximum
parser header, PMAC, Ethernet header and two VLAN tags. The netdev takes the
smaller of that capacity and the GRX500 vendor limit, explicitly sets min_mtu
and max_mtu, and preserves the default 1500-byte MTU. Missing or insufficient
capacity fails before PHY/subinterface resources are acquired. MTU changes
use these per-device limits instead of the generic global limit.

The existing CBM register definition documents JSEL=0 as 8 KiB and JSEL=1 as
16 KiB. Driver initialization already selects that bit, the buffer-size mask,
and free-list geometry from CONFIG_CBM_JBO_PKT_SIZE. The target and its
Kconfig defaults now select 0x4000. The 8 MiB jumbo pool is unchanged: nominal
buffer count falls from 1024 to 512 before driver-reserved entries. The 2 KiB
standard pool is unchanged. Queue pressure and throughput in the new mode
remain hardware tests.

For this build, compiled CBM code returns 16190 bytes (16384 minus 194 bytes
of headroom). Compiled datapath code subtracts another 78 bytes: 14 Ethernet,
48 parser, 8 PMAC and 8 VLAN allowance. The resulting capacity is 16112; the
SoC limit caps the netdev at 8000. Its compiled SoC-data object contains
0x00001f40 at the MTU field. These constants leave room for the requested MTU
without depending on whether parser metadata is enabled for a given packet.
PMAC setup disables FCS delivery to the CPU. Hardware interpretation of these
registers still requires validation on the device.

Validation
----------

* test-mtu.py executes the actual CBM capacity, datapath query, netdev limit
  setup and MTU-change functions. 19,183 ASan/UBSan cases cover old/new pool
  sizes, all MTU requests through 9583, missing capacity, stopped providers,
  unchanged device fields on setup failure, and LAN/WAN jumbo transitions.
  Hardware operations are fixtures, and packet transmission is not executed.
* The RX copy/ownership suite passes 18,957 cases with 16 KiB buffers.
* The TX descriptor suite passes 165,906 cases under native ASan/UBSan and
  separately under big-endian MIPS userspace emulation using the actual C
  descriptor layouts. DMA, pool ownership leaves and MMIO remain mocked.
* The first full build caught a CBM_SUCCESS macro unavailable in the datapath
  compilation unit. The code now follows the existing nonzero-error convention;
  the second full build passes. Existing vendor warnings remain.
* Static image checks bind both development images to their Linux/loader ELFs,
  verify the current packaged wireless modules and protected partition flags,
  and require prepared CBM/datapath/Ethernet sources to match this source tree.

The results and exact input/output hashes are in mtu-results.json. The new
images are development artifacts, not stock-web upload containers. The earlier
factory candidate remains withdrawn. Ethernet and Wi-Fi operation, full
peripheral behavior, NAND/persistence, and reliable serial-free installation
and recovery still require device testing. No no-brick guarantee is claimed.
