#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Append hashes of the exact kernel and rootfs tar members before fwtool metadata."""

import hashlib
import io
import os
from pathlib import Path
import sys
import tarfile


DIRECTORY = "sysupgrade-tplink_archer-ax3000-v1/"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} SYSUPGRADE-TAR")

    image = Path(sys.argv[1])
    with tarfile.open(image, "r") as archive:
        members = archive.getmembers()
        hashes = []
        for name in ("kernel", "root"):
            found = [member for member in members if member.name == DIRECTORY + name]
            if len(found) != 1 or not found[0].isfile():
                raise ValueError(f"expected one regular {name} member")
            data = archive.extractfile(found[0]).read()
            hashes.append(f"{name} {hashlib.sha256(data).hexdigest()}\n")
        if any(member.name == DIRECTORY + "SHA256SUMS" for member in members):
            raise ValueError("SHA256SUMS member already present")

    content = "".join(hashes).encode("ascii")
    with tarfile.open(image, "a") as archive:
        member = tarfile.TarInfo(DIRECTORY + "SHA256SUMS")
        member.mode = 0o644
        member.size = len(content)
        member.mtime = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
        archive.addfile(member, io.BytesIO(content))


if __name__ == "__main__":
    main()
