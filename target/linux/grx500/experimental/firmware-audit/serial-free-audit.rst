Ethernet-only installation investigation
======================================

Status: a prospective factory container passes the stock checker and its
kernel component passes the stock writer's parser in isolation. There is still
NO verified Ethernet-only installation or recovery procedure, and NO factory
image is published for upload. Existing initramfs/sysupgrade artifacts remain
unsuitable for the stock web interface. Hardware has not been tested.

Firmware identity
-----------------

The US v1.60 support page, checked on 2026-10-21, lists 1.0.6 Build 20230831
as its newest dated firmware. Its download link selects the exact 230831 ZIP
already researched. This verifies the public download, not the firmware version
or modified environment actually installed on an individual router:

https://www.tp-link.com/us/support/download/archer-ax3000/v1.60/

Observed checker and parser behavior
------------------------------------

``test-stock-factory-envelope.py`` pins the existing stock/checker SHA256s,
reuses the isolated QEMU/bubblewrap harness. Its original ten assertions are:

* A stock payload in a legacy MD5 envelope passes ``nvrammanager -c``.
* A changed payload without recalculating that digest fails.
* Recalculating the envelope digest over a damaged uImage passes ``-c``.
  Thus checker acceptance alone does not establish component integrity.
* A mismatched EU product-info fixture still fails the US support-list check.
* Both real OpenWrt initramfs images, each placed after the original metadata
  as a single kernel component, pass the checker.
* The stock ``-u`` parser sends each complete uImage, byte-for-byte, to one
  ``vol_mgmt upgrade_dualvol_stdin kernel`` request. Captured hashes match the
  previously audited baseline and DirectConnect RAM images. No bootloader,
  rootfs, bootcore or firmware component is requested in these two cases.
* Rehashed containers with damaged kernel data fail the writer's CRC check
  before any component is sent to the capture helper.

The expanded suite now passes 22 scoped assertions. Starting the exact stock
ubusd fixes the earlier ``pthread_cancel failed!`` teardown failure; the writer
then exits zero. Wrapped initramfs and kernel/rootfs candidates also pass the
checker and byte-for-byte capture checks. Four no-ubus writer controls still
assert the original exit 255. Even with ubusd, a damaged component can produce
exit zero, so status alone is insufficient. See ``one-shot-audit.rst`` for the
known original-image boot-memory failure, relocation fix and new tests.

For the parser tests, a statically linked host capture program replaces
``/bin/sh`` inside the private read-only root. It never executes shell commands
or ``vol_mgmt``; it only records the component bytes in a temporary directory.
Other child requests, including ``cloud_cleanFwInfo``, are rejected. There are
no flash devices, no network access and no router connection. No MTD/UBI access
attempts appear in the target traces. Test candidate containers and captures
are deleted; the harness does not emit uploadable images.

The legacy path was first identified in direct Ghidra output for
``FUN_0040830c`` and ``FUN_004080e0``. For an unrecognized firmware-type string,
the stock code selects its legacy MD5 branch. The test uses ``fw-type:Legacy``,
the unchanged metadata starting at 0x1014, and component data starting at
0x1127. This is a format experiment, not proof of an installation contract.

Stock bank switching: defaults and mocked control flow
-------------------------------------------------------

The actual extracted stock U-Boot contains these default environment strings,
also present in the vendor ax3000v1 ``sdk.config``:

* ``check_image0=run switchbankA``
* ``check_image1=run switchbankB;setenv update_chk 0;save``
* ``check_image2=run switchbankB``
* ``check_image3=run switchbankA;setenv update_chk 2;save``

The shipped ``vol_mgmt`` reads the currently booted bank from ``/proc/cmdline``,
deletes/recreates the opposite kernel volume, writes it, then sets the kernel
size, active bank and trial state (1 for B, 3 for A). On a trial boot the default
bootloader strings save the original bank's stable state before booting the
trial bank. Stock ``ltqboot`` subsequently marks its own successful startup.

Inference: if these defaults match the device's persistent environment and
environment saves work, an uncommitted trial could return to the original
bank on the next reboot. This is NOT a tested rollback guarantee. Actual free
UBI capacity, kernel-volume expansion, partial-write failures, bootcore pairing,
saved environment integrity and hardware startup remain unknown. The existing
RAM image does not run stock ``ltqboot`` to commit a trial installation.

Other serial-free routes
-------------------------

The vendor configuration disables ``CONFIG_UBOOT_CONFIG_CMD_HTTPD``. The
actual bootloader includes interactive TFTP commands; neither fact establishes
a reset-button-triggered TFTP or HTTP recovery path. The string
``http_upgrade done!`` comes from a generic upgrade routine in
``202-cmd-upgrade.patch`` and is not evidence that an HTTP server is enabled.
TP-Link's generic recovery FAQ explicitly does not cover every router model:

https://www.tp-link.com/us/support/faq/1482/

The stock filesystem enables Dropbear at startup on port 22. Its init script
comments out the ``-L`` session-login option; the shipped binary documents and
parses that vendor option. This does not establish a usable shell or credentials.
Direct Ghidra output is retained, but shell availability on the router has not
been tested. An open SSH port by itself would not answer that question.

The shipped Lua 5.1 compiler successfully disassembles the firmware controller
and ``luci.model.fmup`` bytecode under isolation. ``upgrade_firmware`` delegates
to ``fmup.upd_fm``. The latter calls ``nvrammanager -c`` through ``fork_call``;
only a zero status reaches the ``fork_exec`` call for ``nvrammanager -u``.
This web-dispatch path directly invokes nvrammanager, whereas the separate
``/sbin/sysupgrade`` script also performs check/write stages. These are static
control-flow observations, not execution of the authenticated HTTP upload flow.
Listings and syscall traces are retained with the other analysis artifacts.

Reproduction and remaining work
-------------------------------

Run ``test-stock-factory-envelope.py`` with the same ``--rootfs``, ``--stock``,
``--qemu``, ``--artifacts`` and ``--output`` arguments as the stock checker test.
It additionally requires a native GCC capable of producing a static executable.
``factory-envelope-results.json`` records hashes, outcomes, captured component
identities, exit codes and limitations. Full traces are retained under the
bringup artifacts' ``verification/factory-envelope-results`` directory.

The updater teardown issue is resolved in isolation, and ten mocked bank-switch
cases now expose non-atomic environment updates. Actual mutation, overlay
creation, bank commitment, hardware boot and recovery remain unverified. The
original unwrapped images also have a reproduced decompression overlap at the
stock flash load address. Consult ``one-shot-audit.rst`` before any further
installation work. No factory upload image is ready.
