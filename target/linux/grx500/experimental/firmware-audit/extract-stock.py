#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract CRC-checked components of the inspected AX3000 US 230831 image.

This deliberately pins one researched input rather than guessing the layout
of other TP-Link releases. It reads files only and never executes firmware.
The output directory must not exist. Firmware remains outside the source tree.
"""

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import struct
import zlib


SHA256 = "96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b"
OFFSETS = (0x1127, 0x116f, 0xd9af, 0x25f0f, 0x25f4f, 0x45f4f, 0x16f0f8f)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def uimage(data, offset):
    header = data[offset:offset + 64]
    if len(header) != 64:
        raise ValueError("truncated uImage header")
    h = struct.unpack(">7I4B32s", header)
    payload = data[offset + 64:offset + 64 + h[3]]
    if h[0] != 0x27051956 or len(payload) != h[3]:
        raise ValueError("uImage magic or payload size mismatch")
    if zlib.crc32(header[:4] + bytes(4) + header[8:]) != h[1]:
        raise ValueError("uImage header CRC mismatch")
    if zlib.crc32(payload) != h[6]:
        raise ValueError("uImage payload CRC mismatch")
    return payload, {"offset": hex(offset), "name": h[11].rstrip(b"\0").decode(),
                     "payload_size": h[3], "load": hex(h[4]), "entry": hex(h[5]),
                     "os": h[7], "architecture": h[8], "type": h[9],
                     "compression_header": h[10], "payload_sha256": sha(payload),
                     "header_crc": "passed", "payload_crc": "passed"}


def decompress(data):
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    raw = decoder.decompress(data, max_length=64 * 1024 * 1024)
    if not decoder.eof:
        raise ValueError("incomplete or oversized LZMA stream")
    return raw, decoder.unused_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    data = args.firmware.read_bytes()
    if sha(data) != SHA256:
        parser.error("input differs from the researched AX3000 US 230831 payload")
    if args.output_directory.exists():
        parser.error("output directory must not exist")
    images = {offset: uimage(data, offset) for offset in OFFSETS}
    kernel, kernel_tail = decompress(images[0x16f0f8f][0])
    if any(kernel_tail):
        raise ValueError("unexpected nonzero kernel padding")
    size = struct.unpack_from(">I", kernel, 0x414)[0]
    dtb = kernel[0x410:0x410 + size]
    if dtb[:4] != b"\xd0\x0d\xfe\xed" or len(dtb) != size:
        raise ValueError("invalid embedded DTB")
    # GPHY Firmware is a uImage multi-image with one length then a zero terminator.
    multi = images[0x25f4f][0]
    length, terminator = struct.unpack_from(">II", multi)
    if terminator or length != len(multi) - 8:
        raise ValueError("unexpected GPHY multi-image length table")
    gphy_container, tail = decompress(multi[8:])
    if tail:
        raise ValueError("unexpected trailing GPHY LZMA bytes")
    gphy_raw, gphy_header = uimage(gphy_container, 0)
    if gphy_header["name"] != "GRX500 V1.1 GPHY BE" or len(gphy_raw) != 65536:
        raise ValueError("unexpected GPHY image")
    uboot, uboot_tail = decompress(images[0xd9af][0])
    rootfs = images[0x45f4f][0]
    if rootfs[:4] != b"hsqs":
        raise ValueError("expected little-endian SquashFS rootfs")
    outputs = {
        "kernel.bin": kernel,
        "board.dtb": dtb,
        "rootfs.squashfs": rootfs,
        "uboot.bin": uboot,
        "gphy-container.bin": gphy_container,
        "gphy-raw.bin": gphy_raw,
    }
    report = {
        "schema": 1, "input_sha256": SHA256, "input_bytes": len(data),
        "uimages": [entry[1] for entry in images.values()],
        "embedded_dtb_offset": "0x410",
        "kernel_lzma_trailing_zero_bytes": len(kernel_tail),
        "inner_gphy_header": gphy_header,
        "gphy_container_trailing_hex": gphy_container[64 + len(gphy_raw):].hex(),
        "uboot_lzma_trailing_hex": uboot_tail.hex(),
        "outputs": {name: {"sha256": sha(raw), "bytes": len(raw)}
                    for name, raw in outputs.items()},
        "limitations": [
            "CRC32 and SHA256 identify bytes; they do not authenticate a firmware signature.",
            "Rootfs header declares LZMA but payload starts directly with SquashFS; no extra LZMA step is applied.",
            "Raw GPHY extraction does not establish compatibility with a different driver release.",
            "No per-device Wi-Fi calibration is supplied by this generic update image.",
            "Embedded DT and bootloader defaults do not establish live RAM or partition layout.",
        ],
    }
    args.output_directory.mkdir(parents=True)
    for name, raw in outputs.items():
        (args.output_directory / name).write_bytes(raw)
    (args.output_directory / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"manifest": str(args.output_directory / "manifest.json"),
                      "uimage_crc_checks_passed": len(images) + 1}))


if __name__ == "__main__":
    main()
