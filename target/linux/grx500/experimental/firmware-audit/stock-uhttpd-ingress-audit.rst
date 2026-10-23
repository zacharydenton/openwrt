Stock uhttpd multipart ingress
==============================

The pinned 230831 rootfs contains MIPS ``uhttpd``
(``41368afb8ce60875d8da841dc96158f07a1cc19d666fc7d20e1b909491875fb1``)
and ``ubusd``
(``7616442b0c7d5c8ca1e18a3491b9bfb19b78661c07edda6a8a69cb1cb42332d3``).
The stock ``/etc/config/uhttpd`` sets three **concurrent requests**, a
120-second CGI timeout and a 30-second network timeout; it does not set a
request-body size limit. The server's startup requires ubus and a ``sysmode``
UCI entry; that entry is absent from the extracted rootfs.

``verify-stock-uhttpd-ingress.py`` runs both exact vendor binaries under QEMU
in disposable bubblewrap filesystems. It supplies a temporary router-mode
``sysmode`` entry, a private ubus socket, and a synthetic static CGI that only
records stdin. The stock server binds a temporary loopback port; neither the
stock upgrade program nor MTD devices are available in the sandbox. The
harness sends the exact 9,038,490-byte multipart body already bound to the
passing LuCI parser test, first without an ``Expect`` header and then with
``Expect: 100-continue``. Both requests returned HTTP 200, and each captured
body matched the submitted SHA-256
``0714489d0e6437af066df4373dbbc6f1a8604b6c363ab73cd94cc51fe37aa630``.
The body contains the 9,038,110-byte **unapproved laboratory** factory
container.

The separate ``stock-web-route-audit.rst`` executes the stock LuCI multipart
parser, file handler and upgrade dispatch against these same bytes, with
external checker/writer commands intercepted. Together these tests show that
the shipped HTTP server can receive the request and that the stock LuCI
handler can parse it. They do not run a single authenticated HTTP request all
the way through the stock LuCI dispatcher. They also do not establish the
user's current router firmware version, runtime upload-size UCI override,
physical flash layout, kernel boot, Ethernet, Wi-Fi, or rollback behavior.
Do not upload this image on the strength of this test.

Reproduce from the OpenWrt repository root::

  python3 target/linux/grx500/experimental/firmware-audit/verify-stock-uhttpd-ingress.py \
    --rootfs /home/zach/code/archer-ax3000-bringup/stock-rootfs \
    --stock /home/zach/code/archer-ax3000-bringup/stock-230831.bin \
    --qemu /home/zach/code/archer-ax3000-bringup/web-upgrade-audit/usr/bin/qemu-mips-static \
    --factory /home/zach/code/archer-ax3000-bringup/one-shot-audit/env-geometry-final/UNAPPROVED-factory.bin \
    --route-report target/linux/grx500/experimental/firmware-audit/stock-web-route-results.json \
    --output target/linux/grx500/experimental/firmware-audit/stock-uhttpd-ingress-results.json \
    --artifacts /home/zach/code/archer-ax3000-bringup/one-shot-audit/uhttpd-ingress
