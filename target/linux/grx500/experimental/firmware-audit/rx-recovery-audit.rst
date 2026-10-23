Wi-Fi RX ownership and integrated build
=======================================

Three Wi-Fi recovery defects are fixed in patch
120-rx-buffer-ownership.patch. The ordinary OpenWrt target also completes a
full image build with the earlier bank-parser and receive-boundary fixes.
This remains development work: neither image has booted a physical router,
and no factory upload or successful Ethernet/Wi-Fi operation is claimed.

Reproduced ownership failures
----------------------------

The original RX-data preallocator set its cleanup flag only after all buffers
were allocated. Failure in a later slot returned without releasing earlier
allocations/mappings. The driver's lifecycle macros record a step only after
success, so the failing start step cannot rely on automatic step cleanup.
The fault test reproduces a failure in slot two leaving one allocation and
one mapping live. Current code sets ownership before starting and explicitly
unwinds on failure. Cleanup clears freed slot pointers and DMA addresses so
later failures/retries cannot reuse dangling pointers.

Received fragments leave their ring slots; those slots receive replacement
buffers. The old cleanup freed the replacements, then cleared the fragment
chain pointers without freeing the fragments. A two-fragment fixture reproduced
two live, unmapped buffers after cleanup. Current cleanup frees that chain
separately. These fragments must not be unmapped a second time.

The RX buffer-recovery routine created a HOST_DSC on the stack, assigned its
index, payload address and frameInfo3, but left frameInfo0/frameInfo1 undefined.
The ring publisher copies all five fields. A poisoned-stack test reproduces
0xfefefefe in both unassigned fields. The descriptor now starts zeroed.

Verification scope
------------------

* rx-ownership.py executes the actual allocation, preallocation, fragment-free
  and cleanup functions with mocked allocation/DMA leaves. Nineteen cases cover
  failure at every allocation/mapping slot, complete initialization, repeated
  cleanup, retained fragments and the externally owned fast-path branch.
  ASan/UBSan pass. This does not execute firmware, interrupts or real DMA.
* rx-recovery-descriptor.py executes the actual recovery routine and HOST_DSC
  declaration. Eleven cases verify initialized fields, pointer offsets,
  allocation failure requeue, empty lists and zero budgets. Stack poisoning and
  ASan/UBSan pass. Field-position macros are fixtures; this is not an independent
  firmware ABI or hardware ring test.

Full build and artifact binding
-------------------------------

The first integrated build stopped at an interactive Kconfig question for
GRX500_FACTORY_TRIAL. The ordinary target configuration now explicitly disables
it. Its second ``make -j8 V=s`` completes, including kernel, wireless modules,
modpost, root filesystem, initramfs and relocated kernel images. Existing vendor
warnings remain. The separate factory variant retains its intentional opt-in
configuration, but its earlier upload candidate remains withdrawn.

verify-image.py and verify-sysupgrade.py bind both output images to their
Linux and relocation-loader ELFs and pass the static ingredient/clock checks.
The additional integrated content audit reads each image and verifies:

* current first-boot/upgrade scripts, including the closed acceptance gate;
* current wireless modules after reproducing OpenWrt's strip-kmod.sh recipe;
* compiled read-only flags for bootloader, both environment copies, GPHY,
  calibration and reserved partitions;
* absence of the factory-install opt-in marker.

The initial module comparison rejected raw debug modules versus packaged,
stripped modules. Reproducing the actual strip recipe gives exact byte matches
in both images; this was an audit-method correction, not a firmware change.
Prepared prom.c and cbm.c also match the current source files.

Development artifacts and bound ELFs are retained under
``artifacts/development-rx-recovery`` with hashes and reports. They are not
stock-web installation containers and are not approved for installation.
The full objective remains outstanding: real boot and NAND behavior, Ethernet,
both radios and their complete capabilities, peripheral operation, persistent
settings, automatic acceptance and reliable fallback still need validation.
