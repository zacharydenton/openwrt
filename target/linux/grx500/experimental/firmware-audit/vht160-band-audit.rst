5 GHz-only VHT 160 MHz advertisement
=====================================

The exact stock driver returns true from ``hw_get_vht_160mhz_support`` for
either Gen6 radio. The native band initializer previously called the VHT
160 MHz and short-GI helpers for every supported band. This made the 2.4 GHz
wiphy advertise 160 MHz despite that width belonging to the 5 GHz channel
plan. The stock userspace channel map also lists 160 MHz centers only for
5 GHz channels.

Patch ``105-vht160-only-on-5ghz.patch`` gates those two helpers on the 5 GHz
band template. The existing HE setup already has a separate 5 GHz width guard,
so 5 GHz HE/VHT 160 MHz stays available and 2.4 GHz HE40 is unchanged.

Both package builds and full images complete. The prepared source in each
checkout contains the new guard. The retained MIPS module disassembly has
``_cfg80211_band_5ghz`` at data offset 0x17d0 and the 2.4 GHz template at
0x182c. At ``wv_cfg80211_init_band+0x224``, the compiled pointer comparison
branches to the VHT 160 MHz calls only on equality with the 5 GHz template;
the other path reaches HE setup without those calls. The rebuilt sysupgrade
audits require both Wi-Fi modules and the exact module autoload parameters,
and their packaged ``mtlk.ko`` hashes match the compiled package output.

``vht160-band-results.json`` binds the patch, prepared source, MIPS module,
disassembly, build logs and both image audits. This establishes the intended
advertised capability in the build, not 160 MHz operation, regulatory approval,
association or throughput on the user's router. Those require device tests.
