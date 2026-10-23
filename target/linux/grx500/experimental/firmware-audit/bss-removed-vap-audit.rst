BSS confirmation after VAP deletion and reserve reuse
=====================================================

The stock WAVE600 BSS confirmation handler assumed every confirmed descriptor
still had a VAP. A confirmation arriving after dynamic VAP deletion took the
``the_trap`` path and requested a whole-card reset, despite firmware having
returned that descriptor. Patch
``package/kernel/iwlwav-stock/patches/244-bss-confirm-removed-vap.patch``
keeps the existing global-stop behavior (mappings remain for reset), but on
the ordinary live-event path it unmaps the confirmed descriptor, consumes an
accepted skb, recycles the ring slot and processes reserve entries. It skips
cfg80211 and core callbacks when the original VAP is gone. It does not claim
to synchronize a VAP pointer already acquired by another callback.

The same handler copied a reserve frame's metadata into the confirmed mirror
before calling ``mtlk_core_on_bss_cfm`` for the original frame. The core uses
the original extra-processing type to wake a null-data ACK waiter, and the
original probe-response address/subtype to clear pending probe state. Patch
``245-bss-confirm-original-metadata.patch`` saves those four values before
the reserve swap and passes them to the original core. It leaves the new
reserve submission's metadata intact.

Evidence
--------

``tests/bss-removed-vap.py`` compiles and executes the actual full handler
with mocked descriptor lists, DMA, cfg80211 and firmware submission. On the
pre-244 source it reproduces the forced reset. On the post-244/pre-245 source
it reproduces the wrong metadata. With both patches it passes removed-VAP
cases with empty, stale and live reserve queues, a normal AP confirmation,
global-stop deferral and invalid-index reset. All before/after cases pass
native ASan/UBSan and big-endian MIPS QEMU. The prepared ``hw_mmb.c`` is
byte-identical in development, factory and optional DirectConnect builds,
SHA-256 ``8f2d4ffd78d6d2c4a4d8b338e56d4849e72d7989ba7137774b5fe88a3aaa4b04``.

All three complete OpenWrt builds pass on upstream OpenWrt
``d014acb494001606ce78720e240892e840302a9d``. Both ordinary builds package the
same stripped ``mtlk.ko`` (SHA-256
``abfa9f295562526c7231730ca3d751df6cd5bb3b987506317eeec0ba6f79a006``).
The development, factory and DirectConnect RAM/sysupgrade image audits and
their compiled relocation-loader handoff checks pass. The REA-bound stock
U-Boot argument-layout check passes for all six loaders with negative
controls. Factory first-boot prerequisites and 352 matching source inputs
pass. The optional DirectConnect source export and UMT host harness still
pass; ``fastpath=0,0,0`` remains its default.

The latest **unapproved** laboratory factory container is 9,040,227 bytes,
SHA-256 ``e2cb8199461d7555ad9df732d585203d088e46d6d7b23d361b3f3d6a1adb6b32``.
The isolated pinned stock checker/writer suite passes 24 cases, including
exact-byte checker acceptance and capture of its kernel and rootfs. The stock
LuCI route preserves the container and dispatches checker before writer;
stock uhttpd accepts the exact 9,040,607-byte multipart request in both
tested modes. No flash command runs in these tests. Exact artifact and report
hashes are recorded in ``bss-removed-vap-results.json``; full outputs are in
``/home/zach/code/archer-ax3000-bringup/bss-removed-vap-audit/``.

The AP netdev still unregisters before its core serializer stops, and the
hardware callback path still resolves VAP handles without an in-flight
reference. ``vap-rtnl-lifetime-audit.rst`` also shows that dynamic VAP add
and delete run netdev registration across an RTNL-owning ioctl thread and a
serializer kthread. These patches do not close those defects. No router has
booted these images; Ethernet, both radios, flash writes, first-boot
commitment and stock-bank recovery remain untested. This factory container
must not be uploaded to the user's router.
