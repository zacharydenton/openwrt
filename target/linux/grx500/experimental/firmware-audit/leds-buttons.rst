AX3000 front-panel GPIO evidence
===============================

These assignments come from the DTB embedded in the official AX3000(US) V1
230831 kernel (stock-board-410.dtb), not a generic GRX350 reference board. The
manifest's raw properties retain the DTB source offsets and bytes.

All LEDs use active-high gpio0 (physical controller0x16c00000):

* Power: pin21, stock blue:power, default on.
* LAN: pin9, stock blue:lan.
* USB: pin11, stock blue:usb_2, exposed as blue:usb.
* Internet blue: pin7; internet orange: pin6.
* 2.4GHz: pin1, stock blue:wlan_2g, exposed as blue:wlan2g.
* 5GHz: pin4, stock blue:wlan_5g, exposed as blue:wlan5g.

Buttons are active-low, polled every100ms:

* LED toggle: gpio1 pin4 (global36); stock KEY_WLAN238.
* Combined WPS/Wi-Fi: gpio0 pin8; KEY_WPS_BUTTON529.
* Reset: gpio0 pin22; KEY_RESTART408.

The misleading stock ``wifi`` node name is resolved by the actual firmware's
``lib/modules/3.10.104/gpio-button-hotplug.ko``: its big-endian .rodata key map
at offset0x70 contains keycode0xee and a relocation to .rodata.str1.4+0x418,
whose string is ``ledswitch``. The modern board uses KEY_LIGHTS_TOGGLE and an
/etc/rc.button/lights_toggle handler, using OpenWrt's persistent leds_off
setting and LED service turnon/turnoff operations.

Stock /etc/hotplug.d/button/40-wireless acts on WPS releases: less than two
seconds starts WPS, at least two seconds toggles the radios. The modern
/etc/rc.wps/00-grx500-combined intercepts long releases and invokes OpenWrt's
rfkill script; short releases continue to the normal WPS AP handler. It also
suppresses the generic WPS client's five-second timeout for this combined key.
This agrees with the official US V1 manual, printed page6:
https://static.tp-link.com/2019/201909/20190920/1910012593_Archer%20AX3000(US)1.0_UG_V1.pdf

gpio-button-hotplug handles these polled bindings; no GPIO IRQ controller is
required. Reset and WPS retain their stock key codes.

grx500-ax3000-leds-keys.dtsi defines the LEDs and buttons, and power supplies
OpenWrt's boot, running, failsafe and upgrade aliases. The separate stock
power output-high hog is not duplicated because gpio-leds owns that line.
Default LED configuration maps blue:lan to br-lan and blue:internet to wan.
USB uses the usbport trigger for usb1-port1 and usb2-port1, the two root
hubs of the sole enabled xHCI controller.

/usr/libexec/grx500-leds binds each radio LED to the first active AP or STA
interface reported by network.wireless status for that configured band.
It uses runtime ifname values and config.band, not assumed phy indices or
interface names. The procd service refreshes bindings on the existing
netifd.wireless.done event and debounced net hotplug events. Native Wave600
full-MAC radios do not provide mac80211 PHY LED triggers, so these bindings
use the generic netdev link/tx/rx trigger. Multiple BSSes on one band share
one physical LED; activity reflects the first reported active interface.

The same service watches only /sys/class/net/wan/carrier once per second.
Orange internet indicates no physical WAN link; blue internet retains its
kernel netdev link/traffic trigger. This is a link indication, not an
Internet reachability test. The watcher reads the orange LED brightness
and changes it only when necessary, including after the LED service resets
outputs. No iw/ubus polling occurs in that loop. The physical LED toggle
sets the normal persistent leds_off flag, refreshes radio bindings and
suppresses the orange output through a RAM marker.

Shell syntax checks passed. A host fixture with the built host jshn tool
verified reordered runtime PHY/interface names, disabled-radio teardown,
and global LED-off behavior without touching live sysfs.


The complete board DTS compiles without dtc warnings. Wiring, polarity and
button behavior still need physical verification on the user's hardware.
