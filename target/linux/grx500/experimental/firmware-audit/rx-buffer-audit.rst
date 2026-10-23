Ethernet and Wi-Fi receive-buffer audit
======================================

Two receive-buffer defects were reproduced in the actual C code and fixed.
These results are software evidence. No hardware packet exchange, radio
association, boot or recovery test was performed. The factory upload candidate
remains withdrawn; these changes do not remove the installation release hold.

Ethernet CBM copy capacity
-------------------------

build_skb_grx500 now copies hardware data into a Linux-owned allocation and
returns the hardware buffer. Its callback retains a legacy frag_size argument
that includes aligned skb_shared_info space. That metadata lives in the new
Linux allocation, not inside the hardware pool. The old bound compared the
entire frag_size to the hardware capacity and rejected valid trailing data.

The linked MIPS vmlinux has sizeof(skb_shared_info)=248, aligned to 256 bytes
with this kernel's 32-byte cache alignment. Consequently the old check rejected
copy lengths above 1792 in a 2048-byte standard buffer, and above 7936 in an
8192-byte jumbo buffer, even though the data fits. This does not demonstrate
that ordinary 1500-byte Ethernet traffic failed; actual descriptor offsets,
parser metadata and the pool selected determine the affected frame lengths.

The fixed check subtracts metadata overhead before comparing the copy length
with hardware capacity. It first checks for underflow. The helper still checks
pool membership, requires a buffer-base pointer, synchronizes CPU ownership,
copies data and returns the CBM buffer exactly once after a successful copy.

tests/test-cbm-rx.py extracts the production helper. Its sanitizer harness
uses bounded standard/jumbo arrays, records the DMA/ownership calls and checks
the returned payload. All 10765 cases pass: every data length through each
pool limit, oversized buffers, zero/underflow lengths, allocation failure,
invalid address/alignment and DMA translation failure. The pre-fix helper fails
the valid-capacity case. The MIPS cbm.o cross-compiles with existing unrelated
driver warnings. The harness does not emulate DMA/cache coherency or IRQ timing.

Wi-Fi mapping versus allocation
-------------------------------

The WAVE RX data handler maps data_ind->size bytes for DMA, but validated the
received offset+length only against skb tailroom. dev_alloc_skb can provide
extra tailroom through allocation rounding. That padding does not extend the
DMA mapping and must not be delivered as received packet data.

The reproduced example has a 4096-byte mapping, 4160 bytes of allocated room,
a Gen6 offset of 15 and a data length of 4095. The previous branch accepts all
4110 bytes. The new branch requires the total to fit BOTH the mapped size and
the available allocation. Rejected descriptors follow the existing buffer
remapping/return path. Logging now reports both limits. This does not prevent
malfunctioning hardware from writing beyond a mapping; it prevents the driver
from accepting those lengths as valid data.

package/kernel/iwlwav-stock/tests/rx-dma-bounds.py executes the actual rejection
branch with mapping/allocation fixtures. It checks the reproduced example and
666384 combinations of six mapping sizes, allocator padding/shortfalls, all
16 Gen6 offsets and lengths through the boundaries. ASan/UBSan pass. These are
branch tests, not execution of the entire RX handler or firmware. The package
build applies both patches and compiles/links mtlk.ko and mtlkroot.ko, including
modpost. Existing vendor-source warnings remain.

Reproduction
------------

From the OpenWrt tree::

  python3 target/linux/grx500/tests/test-cbm-rx.py
  python3 package/kernel/iwlwav-stock/tests/rx-dma-bounds.py \
    build_dir/target-mips_24kc_musl/linux-grx500_generic/iwlwav-stock-6.0.8.0.87.0.7
  make package/kernel/iwlwav-stock/compile -j8 V=s

rx-buffer-results.json records source/object/module hashes and retained logs.
Current source and compiled objects/modules include the changes. Retained
historical firmware images do not; no replacement factory image is published.
