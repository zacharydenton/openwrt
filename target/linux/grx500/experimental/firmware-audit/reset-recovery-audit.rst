Reset and recovery coverage
===========================

Ethernet, both Wi-Fi radios and recovery remain release requirements. No
hardware test has been performed, and no factory upload is recommended.
An intact stock bank does not by itself guarantee recovery: the router must
reset, its bootloader must select that bank, and NAND/environment writes must
have left it bootable.

What the shipped kernel actually enables
---------------------------------------

``extract-stock-config.py`` reads the pinned US 230831 update, checks the
kernel uImage header and payload CRCs, decompresses the kernel and extracts
its embedded IKCONFIG gzip stream with its CRC and adjacent end marker.
The 90,367-byte configuration contains 2,823 settings and has SHA256
``fe638a76e0757468a9201dbdd9840a96b73a3563f5027ef834f0f404fd62f540``.
Linux's existing ``scripts/extract-ikconfig`` independently produces exactly
the same bytes from the previously verified raw kernel.

The actual downloaded kernel has ``CONFIG_WATCHDOG`` disabled, as well as
``CONFIG_LOCKUP_DETECTOR``, ``CONFIG_DETECT_HUNG_TASK`` and
``CONFIG_PANIC_ON_OOPS``. The product's GPL kernel.config agrees about the
watchdog. This is stronger evidence about the shipped Linux configuration
than the presence of generic SDK driver patches or installed watchdog scripts.
It does not exclude an independent reset mechanism in bootcore or U-Boot,
nor identify the firmware currently installed on the user's device.

The embedded stock DT advertises ``lantiq,wdt-xrx500`` at
``/ssx6@12000000/watchdog@0,0``. The SDK patch 8019 instead registers
``lantiq,grx500wdt``. Neither the node nor that source proves a driver runs.
Patch 8026 also depends on vendor watchdog-framework changes and can panic
when userspace invokes operations from the wrong CPU. Its cross-CPU access
uses the GIC OTHER selector, which the modern interrupt controller protects
with its own private lock. These patches are not a verified drop-in driver
for this port and have not been enabled.

Current port coverage
---------------------

The integrated development kernel enables ``CONFIG_PANIC_ON_OOPS`` and sets
``CONFIG_PANIC_TIMEOUT=1``. It has no selected hardware watchdog driver:
``CONFIG_WATCHDOG_CORE`` and the soft/hard lockup detectors are disabled.
A panic timeout helps only if panic/restart code can execute successfully.

The experimental trial worker retries readiness and requests an ordinary
userspace reboot after failure. Its 1800-second counter measures retry sleeps,
not a guaranteed deadline: prerequisite commands or ``sync`` can block, and
the worker cannot run during an early boot hang or kernel hard lockup.
The early hook now marks a failed environment-config temporary-file creation
so the late worker is scheduled if userspace reaches it. Native and packaged
MIPS shell fault cases exercise that path; they do not test the actual reboot.
The production acceptance function remains closed, preventing readiness
alone from committing an unverified bank. That guard prevents one unsafe
commit path; it does not establish a successful boot or recovery mechanism.

Bootloader defaults suggest the previous bank is selected after resetting an
uncommitted trial, subject to the saved environment and writes behaving as
expected. Existing tests execute mocked bank-control flow, not NAND resets or
power cuts. No tested automatic reset spans the relocation loader, early
kernel startup, driver probing and userspace acceptance. A power cycle might
reach the previous bank under the documented contract, but this remains an
untested inference and is not a no-brick guarantee.

Release evidence still needed
-----------------------------

For the exact proposed upload image, hardware evidence must establish boot,
LAN management reachability and packet forwarding, WAN/LAN isolation, both
radios with association and real data transfer, the requested radio/security
capabilities, and persistence/peripheral behavior. Recovery additionally needs
failed-boot and interrupted-write tests showing that an intact stock bank is
actually reachable without serial intervention. Compilation, simulated DMA
and host decoder tests cannot substitute for those observations.

Reproduce the new static extraction with::

  python3 extract-stock-config.py /path/to/stock-230831.bin /new/output-directory

The output directory contains the full configuration and a manifest binding
it to the exact firmware/kernel bytes. ``reset-recovery-results.json`` binds
the retained independent comparison and the source/configuration inputs.
No new firmware image was built or released for this documentation/evidence
change; the last integrated development image remains unchanged.
