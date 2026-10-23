AX3000(US) V1.6 official firmware provenance
===========================================

Checked on 2026-10-23 against TP-Link's United States Archer AX3000 V1.60
download page:

https://www.tp-link.com/us/support/download/archer-ax3000/v1.60/

The page lists ``Archer AX3000(US)_V1.6_1.0.6 Build 20230831``. Its download
link points to the same ``Archer AX3000(US)_V1_230831.zip`` URL previously
used for the V1-family reverse engineering:

https://static.tp-link.com/upload/firmware/2023/202309/20230906/Archer%20AX3000%28US%29_V1_230831.zip

A fresh download was compared byte-for-byte with the pinned local archive.
Both ZIPs have SHA-256
``6198caa78034f69a029b1e4009c2a69f4c36ea9e673e75338b50925543198846``.
Their embedded ``ax3000v1_intel-up-ver1-0-6-P1[20230831-rel67466]_sign.bin``
has SHA-256
``96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b``.
The V1.60 page's GPL link points to the same
``ax3000v1_GPL_3.tar.gz`` URL used for vendor-source comparisons:

https://static.tp-link.com/upload/gpl-code/2022/202211/20221107/ax3000v1_GPL_3.tar.gz

This proves that the V1.60 page's latest listed update uses the exact
firmware bytes examined by the port. It does not prove the firmware version
currently installed on the user's individual v1.6 unit, physical board
wiring, a successful OpenWrt boot, or safe stock-web installation.

``v16-baseline-results.json`` records the matched hashes. Reproduce with
``verify-v16-baseline.py --v16-zip NEW_DOWNLOAD --pinned-zip PINNED_ZIP
--output REPORT``. A one-byte changed download was rejected as a negative
control.
