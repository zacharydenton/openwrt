Stock AX3000 web upload route
============================

The pinned stock 230831 firmware's LuCI upgrade page submits a ``.bin`` file
under the multipart field ``image``. Its MIPS Lua controller installs a file
handler that writes that field to ``/tmp/firmware.bin``. The controller calls
the stock ``fmup`` module, which requests ``nvrammanager -c`` on that file and,
only after a zero checker result, requests ``nvrammanager -u`` on the same file.
The controller's default upload limit is 32 MiB plus 6164 bytes; the tested
container is 9038110 bytes. A device-specific UCI override was not read.

``verify-stock-web-route.py`` runs the genuine pinned ``luci.http`` request,
multipart protocol parser, controller, ``fmup`` and ``luci.util`` bytecode
with the stock MIPS Lua interpreter under QEMU and bubblewrap. It feeds a
9038490-byte multipart body containing the browser form's ``operation``,
``keep`` and ``image`` fields in 4 KiB chunks. The actual parser invokes the
controller's file handler. The captured ``/tmp/firmware.bin`` has the same
SHA-256 and 9038110-byte count as the image field. The mapped ``upgrade/firmware``
operation requests the checker and writer in order. A second run supplies a
nonzero checker result and confirms that no writer request follows. External
commands are intercepted; a separate test
has already run the exact stock checker and writer parser against those bytes
without flash access. ``stock-web-route-results.json`` binds every input,
the route fixture, the captured bytes and the prior parser report.

This validates the Lua multipart parser, file handler and dispatch. A separate
``stock-uhttpd-ingress-audit.rst`` runs the exact stock HTTP server and sends
the same multipart body to a disposable CGI. The tests do not exercise stock
LuCI authentication and dispatch through one live HTTP request, a
device-specific upload-size setting, or the live router state. They do not
boot or write NAND.
The image remains an
unapproved laboratory container, not a safe stock-web upload.
