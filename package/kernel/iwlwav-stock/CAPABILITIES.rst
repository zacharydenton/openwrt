Native wireless capability audit
===============================

The evidence below is static source/firmware analysis and cross-compilation.
It is not a hardware acceptance result. Paths refer to the verified, prepared
stock source unless explicitly identified as TP-Link rootfs or OpenWrt.

HE and 160 MHz
--------------

cfg80211.c:set_he_support constructs native HE capabilities with antenna/NSS
limits read from EEPROM and 160 MHz gated by hw_get_vht_160mhz_support on the
5 GHz band only. The same band guard keeps VHT 160 MHz and short-GI flags off
the 2.4 GHz wiphy. MCS0-11
maps exist for both <=80 and contiguous 160 MHz. The A0/B0 capabilities are
corroborated by Intel's later GRX500 mac80211.c A0/B0 tables; D2-only capabilities
are not copied onto A0. The exact firmware retains its 18-byte MAC/PHY UMI
field, eight MCS bytes and thirteen PPE bytes. The adapter fixes the old host
buffer truncation without changing that wire structure.

The TP-Link rootfs lib/wifi/tplink_intel.sh:hostapd_conf_11ax contains draft-era
HE settings, some broader than the later A0/B0 tables (for example STBC/DCM).
Those strings alone do not establish silicon or firmware support. The driver
advertises the corroborated A0/B0 table, not the later D2 feature set. Matching
source explicitly leaves 80+80 channel configuration unimplemented and TWT
commands unsupported. Neither is advertised.

MU-MIMO and OFDMA
----------------

The source defaults HE-MU operation to enabled, but the actual TP-Link rootfs
radio_commands explicitly sends sHeMuOperation 0. Its pre_up_commands also
sets sMuOperation from the MU-MIMO UI switch. Consequently, the source default
comment is insufficient evidence that stock OFDMA is active.

Native wave_radio_ap_start now calls the existing serialized
WAVE_RADIO_REQ_SET_MASTER_CFG path: HE AP configuration enables the exact
UM_MAN_HE_MU_OPERATION_CONFIG_REQ command; native VHT/HE MU-beamformer
capabilities enable UM_MAN_MU_OPERATION_CONFIG_REQ. These are existing matched
firmware commands, not guessed opcodes. They are radio-wide enables, so adding
a legacy BSS does not turn off scheduling used by another BSS. Existing
recovery replays their stored settings. Firmware chooses the actual schedules;
multi-client captures/throughput tests are needed to verify OFDMA/MU operation.

DFS, CAC and channel switching
-----------------------------

Native regulatory requests update the firmware regulatory domain through the
AP wiphy notifier. The country is cached because wiphy registration precedes
master VAP creation; AP start and CAC apply it before channel/TPC programming.
No proprietary INITIAL_DATA request or station-only PHY is needed. Both AP
and optional station wiphys receive a validated permanent MAC derived from
the EEPROM NIC address plus radio index before registration; the original
zero wiphy address is not left for proprietary scripts to fill.

SET_CHAN's isRadarDetectionNeeded follows native channel DFS flags; the exact
source enables radar indications by default for the 5 GHz Gen6 radio. CAC
uses at least the kernel-supplied duration, retaining a longer firmware-region
requirement where applicable. Firmware radar reports reach cfg80211_radar_event;
CAC completion/abort reaches cfg80211_cac_event. Native cfg80211 owns DFS state
propagation and non-occupancy expiration. Stopping an AP cannot mark a radar
channel prematurely usable.

Firmware owns CSA insertion/countdown: beacon_manager.c explicitly says CSA
and Channel Switch Wrapper IEs must not be supplied in the template. Native
channel_switch therefore retains the blocking firmware SET_CHAN sequence and
installs hostapd's beacon_after on completion, updating HE/VHT operation and
probe responses. Notifications run as wiphy work with netdev references.
Actual countdown timing, radar detection, CAC, quiet behavior and multi-BSS
switching require hardware validation.

WPA3, PMF and WPS
----------------

Native hostapd performs SAE; the driver advertises SAE support without claiming
authentication offload. RSN setup recognizes WPA versions rather than only old
PSK AKMs. Native station association allocates an independent firmware SID and
preserves hostapd's AID. Firmware pairwise protection retains the matched UMI
key/station ABI. AP multicast PMF uses host-side BIP-CMAC128/256 or GMAC128/256
with separate IGTK slots and monotonic IPNs; optional station mode uses native
mac80211 software BIP validation. Actual C MMIE serialization has independent
host crypto tests.

AP RX rejects group-addressed robust management from stations and unprotected
robust frames from MFP peers. Firmware is expected to reject bad unicast MICs
and replayed frames before delivering them; the RX ABI has no decoded status
that independently proves this. Negative over-the-air tests are mandatory for
that claim. Standalone deletion of firmware data keys has no identified clear
message; the driver reports unsupported. Peer/VAP teardown and replacement
key installation provide actual removal/rotation; IGTK deletion zeroizes it.

WPS uses normal hostapd beacon/probe IEs and EAPOL. OpenWrt's basic wpad build
has CONFIG_WPS disabled; the device profile must select full wpad-mbedtls.
The WPS button handler also needs its native userspace control utility. WPS
is not a private firmware command and does not apply to SAE-only networks.

Restart and recovery
--------------------

Native stop/start propagates failures and has bounded waits. FAST/FULL firmware
recovery reports station removal before discarding the station database and
reopens the hostapd synchronization gate after all radios restore. It does not
require vendor GET_AID/FREE_AID/SYNC_DONE. The optional dump daemon is not a
requirement for those paths. COMPLETE recovery after repeated failures emits
a standard PCI change uevent after releasing the recovery tasks. The packaged hotplug helper asks netifd to
stop wireless, unloads/reloads the driver with the boot module parameters and
asks netifd to restore the configured interfaces. It requires the existing
per-device calibration files, limits retries to three per ten minutes and
bounds module operations. Its shell flow is tested with mocked commands;
actual teardown/reload, active clients and repeated AP restarts remain device
tests. The module reload affects both integrated radios.
