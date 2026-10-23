#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Select the researched firmware member by content, without unpacking paths."""
import hashlib
from pathlib import Path
import sys
import zipfile

expected = "96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b"
matches = []
with zipfile.ZipFile(sys.argv[1]) as archive:
    for item in archive.infolist():
        if item.file_size != 27201423:
            continue
        data = archive.read(item)
        if hashlib.sha256(data).hexdigest() == expected:
            matches.append(data)
if len(matches) != 1:
    raise SystemExit("expected exactly one identified AX3000 firmware payload")
Path(sys.argv[2]).write_bytes(matches[0])
