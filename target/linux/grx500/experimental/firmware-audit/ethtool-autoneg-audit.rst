Ethernet PHY autonegotiation restart
====================================

The GRX500 Ethernet driver's ``ethtool_ops.nway_reset`` callback was a stub:
it returned success without inspecting the netdev or restarting its PHY. Thus
``ethtool -r lan1`` (and the equivalent request on every other physical port)
reported success while doing nothing.

Repair
------

The callback now returns ``phy_ethtool_nway_reset(dev)``. Linux 6.18's PHY
helper rejects a missing PHY or driver, locks the PHY, calls
``phy_restart_aneg`` and returns the real result. The AX3000 device tree gives
each of ``lan1`` through ``lan4`` and ``wan`` one PHY-backed netdev; SerDes and
datapath-only ethtool tables do not expose this callback.

Verification
------------

``tests/test-ethtool-nway.py`` extracts the production callback and runs it
under ASan/UBSan with a strict helper fixture. Five cases prove exactly one
helper call with the original netdev and unchanged propagation of success,
``-ENODEV``, ``-EIO``, ``-EINVAL`` and ``-EOPNOTSUPP``.

A clean ``make target/linux/compile V=s -j4`` rebuilt Linux 6.18.55 for
MIPS. The compiled Ethernet object contains an ``R_MIPS_26`` relocation from
``nway_reset`` to ``phy_ethtool_nway_reset``. A subsequent full ``make -j4``
rebuilt both development images. Their current image audits pass integrity,
kernel/loader ELF binding, metadata and rootfs checks; exact hashes are in
``ethtool-autoneg-results.json``.

Boundary
--------

The fixture proves callback delegation and error propagation, not MDIO or PHY
behavior. A physical test must run ``ethtool -r`` on all five ports while
observing link drop and renegotiation, then verify negotiated modes, traffic
and error recovery. No factory container was rebuilt or approved for upload.
