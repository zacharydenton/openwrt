#!/usr/bin/env python3
"""Extract only the two byte-verified WAVE sources from TP-Link's GPL bundle."""
import hashlib
import io
from pathlib import Path, PurePosixPath
import sys
import tarfile

VERSION = "lq-wave-300-06.00.08.00.87.00.07.d24084bd3447"
PREFIX = "ax3000v1_GPL_3/intel_GRX350/sdk/7.5.1.50/UGW-7.5.1.50/dl/"
SOURCES = {
    PREFIX + VERSION + ".gpl.wls.src.tar.bz2":
        "c9dcd2b8a97d5cbc303303891daffbedb43acd918971175d980eca9e85212be4",
    PREFIX + VERSION + ".rflib.wls.src.tar.bz2":
        "c389f01f140b7cd6ed62b59a91eb0ad7aa51d9651763443860924fa5019d6745",
}

def main():
    archive, destination = Path(sys.argv[1]), Path(sys.argv[2])
    found = {}
    with tarfile.open(archive, "r|gz") as bundle:
        for member in bundle:
            if member.name in SOURCES:
                data = bundle.extractfile(member).read()
                if hashlib.sha256(data).hexdigest() != SOURCES[member.name]:
                    raise ValueError("WAVE inner archive digest mismatch: " + member.name)
                found[member.name] = data
                if len(found) == len(SOURCES):
                    break
    if set(found) != set(SOURCES):
        raise ValueError("GPL bundle is missing a required WAVE source archive")
    destination.mkdir(parents=True, exist_ok=True)
    for name in SOURCES:
        with tarfile.open(fileobj=io.BytesIO(found[name]), mode="r:bz2") as source:
            for member in source:
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != VERSION + ".wls.src" or ".." in parts:
                    raise ValueError("Unexpected source path: " + member.name)
                if len(parts) == 1:
                    continue
                path = destination.joinpath(*parts[1:])
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(source.extractfile(member).read())
                    path.chmod(member.mode & 0o777)
                else:
                    raise ValueError("Unexpected non-file source entry: " + member.name)
    print("Verified and extracted exact stock WAVE driver and RF library")

if __name__ == "__main__":
    main()
