Ethernet, Wi-Fi and recovery acceptance audit
===========================================

Verdict: no image is ready for stock-web upload. The experimental factory image
with SHA256 abea552e78ba3adfe52323566a3d93c1cc587e56382e727429c754a6c41ecf29
is withdrawn and retained under artifacts/factory/superseded/network-acceptance.
It lacks the source fixes described here. A later factory sysupgrade was built
for static checks, but no stock-web image is approved for upload.
No physical router has been accessed, booted, flashed or network-tested.

Premature commitment
--------------------

The old grx500_trial_health checks establish only startup prerequisites.
Carrier can be present without usable Ethernet TX/RX. Two readable wiphys and
calibration files do not demonstrate AP startup, association or wireless TX/RX;
OpenWrt also disables the radios by default. Running DHCP/SSH processes does
not establish that either service is reachable from a client.

The regression runs the real shell library with all those prerequisites true
but without packet exchange or wireless associations. Before the fix it changes
the saved stable bank in BOTH directions. This loses the intended automatic
stock fallback even though the user's essential networking requirement has
not been established. Successful startup is therefore insufficient to commit.

Current grx500_trial_commit calls a separate grx500_trial_acceptance predicate
before any fw_setenv operation. It requires an explicit root acceptance marker
bound to the current bank and boot ID. The factory-only ``grx500-trialctl``
command writes that marker only after rechecking boot context and startup
prerequisites. The worker gives the tester 30 minutes, then requests reboot
without commitment if no acceptance arrives. This permits manual Ethernet,
Wi-Fi and device testing without treating startup as proof of networking.
It does not automatically validate packet flow, RF behavior, USB or recovery.
Whether timeout or a manual power cycle returns to stock remains untested on
hardware. Preparation can still create an experimental overlay, so no image
is approved for upload.

The transaction tests exercise both the real boot-bound predicate and a
test-only substitution for redundant environment writes. Fifty modeled
scenarios (thirteen unittest groups) pass under native and packaged MIPS shells.
Four additional worker test groups cover acceptance, timeout, preparation
failure and one-shot commit failure. The fixtures do not execute NAND,
real networking, procd or a physical reboot.

Boot-bank ambiguity
-------------------

The original early parser accepted the first rootfsname inside an argument,
then prom_init could overwrite that selection with a later argv entry. It
published only one normalized rootfsname. Consequently the later shell check
for duplicate selectors could not detect the original ambiguity.

The parser now scans whole space-delimited tokens and carries selection state
across the complete argv vector. Malformed or repeated rootfsname tokens,
including two identical banks, cause a sticky error. Unterminated or invalid
argument pointers abort selection. The selected bank is published only after
all arguments pass. A flash kernel refuses to attach UBI without that selector;
initramfs retains its existing no-automatic-attachment behavior.

The actual parser passes ASan/UBSan tests covering both valid banks, unrelated
arguments, duplicate and conflicting selectors within/across arguments,
malformed tokens before/after valid tokens, sticky errors, every truncated
token length and bounded buffers. The changed prom.o cross-compiles and is
bound to the rebuilt factory sysupgrade by the ELF/image audit. No physical
boot is claimed.

Reset and recovery limits
-------------------------

Vendor GPL patch 3017-GRX500-mips-lantiq-common-platform-support.patch writes
RCU offset 0x10 bit 30 for restart. The port's syscon-reboot DT node uses that
same register/bit. The compiled factory configuration enables POWER_RESET_SYSCON,
and Linux's MIPS machine_restart calls do_kernel_restart. This establishes a
source-level route to the reset write, not that the write resets this device.

The compiled factory configuration has WATCHDOG=y but WATCHDOG_CORE is unset
and no platform hardware watchdog driver is enabled. Panic timeout is not a
hardware watchdog and cannot reset a CPU that no longer executes. Early hangs,
failed NAND saves, interrupted writes and actual bank fallback remain untested.
Keeping bootloader/calibration partitions read-only and retaining the old
bank are useful protections, but do not establish non-bricking installation.

Unresolved acceptance
---------------------

Ethernet requires real client traffic in both directions through every LAN
port and WAN, DHCP/management reachability and LAN/WAN isolation. Wi-Fi requires
AP startup and client traffic on both bands, supported HE widths including
160 MHz where permitted, SAE/PMF, key changes, DFS/CAC and recovery. Complete
device acceptance also includes persistent settings, USB, LEDs and buttons.
Installation requires observed boot and fallback behavior, including failed
startup and interrupted installation. None of these physical checks has passed.
The intended eventual installation remains a single stock-web upload; no
serial step has been added to that flow.
