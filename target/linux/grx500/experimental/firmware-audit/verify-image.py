#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check necessary device ingredients in an actual GRX500 RAM image.

Exit 1 means missing prerequisites, 2 malformed/unverifiable input. Exit 0
only means these static checks passed; it never certifies boot or networking.
The supplied ELF must reproduce the image's kernel bytes using OpenWrt's
objcopy recipe. Initramfs and DTB are decoded from the image itself.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import lzma
import zlib
from kernel_transport import decode_kernel


def digest(data):
    return hashlib.sha256(data).hexdigest()


def cpio_files(data):
    pos = 0
    files = {}
    while pos + 110 <= len(data):
        if data[pos:pos + 6] != b"070701":
            raise ValueError("expected uncompressed newc initramfs")
        fields = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16)
                  for i in range(13)]
        length, namesize = fields[6], fields[11]
        if namesize < 1 or pos + 110 + namesize > len(data):
            raise ValueError("invalid CPIO filename")
        name = data[pos + 110:pos + 110 + namesize]
        if name[-1:] != b"\0":
            raise ValueError("unterminated CPIO filename")
        name = name[:-1].decode().removeprefix("./")
        pos = (pos + 110 + namesize + 3) & ~3
        if pos + length > len(data):
            raise ValueError("truncated CPIO entry")
        if name == "TRAILER!!!":
            return files
        if name in files:
            raise ValueError("duplicate CPIO entry: " + name)
        files[name] = data[pos:pos + length]
        pos = (pos + length + 3) & ~3
    raise ValueError("missing CPIO trailer")


def inspect(args):
    image = args.image.read_bytes()
    if len(image) < 64:
        raise ValueError("truncated uImage")
    h = struct.unpack(">7I4B32s", image[:64])
    if h[0] != 0x27051956 or len(image) != 64 + h[3]:
        raise ValueError("uImage magic or length mismatch")
    if zlib.crc32(image[:4] + bytes(4) + image[8:64]) != h[1]:
        raise ValueError("uImage header CRC mismatch")
    if zlib.crc32(image[64:]) != h[6]:
        raise ValueError("uImage payload CRC mismatch")
    if h[7:11] != (5, 5, 2, 3):
        raise ValueError("expected Linux/MIPS/kernel/LZMA uImage")
    raw, transport = decode_kernel(h, image[64:], args.loader_elf, args.cross_compile)

    # The ELF's symbol evidence is accepted only after byte-for-byte binding.
    with tempfile.TemporaryDirectory(prefix="grx500-audit-") as directory:
        binary = Path(directory) / "kernel.bin"
        command = [args.cross_compile + "objcopy", "-O", "binary", "-S"]
        for section in (".reginfo", ".notes", ".note", ".comment",
                        ".mdebug", ".note.gnu.build-id"):
            command += ["-R", section]
        subprocess.run(command + [str(args.elf), str(binary)], check=True,
                       capture_output=True)
        kernel = binary.read_bytes()
    if raw[:len(kernel)] != kernel:
        raise ValueError("supplied ELF does not reproduce the image kernel")
    dtb = raw[len(kernel):]
    spec = importlib.util.spec_from_file_location(
        "board_audit", Path(__file__).with_name("board-audit.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tree = module.parse_dtb(dtb)
    clock_spec = importlib.util.spec_from_file_location(
        "clock_audit", Path(__file__).with_name("clock-audit.py"))
    clock_module = importlib.util.module_from_spec(clock_spec)
    clock_spec.loader.exec_module(clock_module)
    clock_evidence = clock_module.audit_clocks(dtb, Path(__file__).resolve().parents[2])
    clock_module.audit_compiled_clocks(clock_evidence, kernel, args.elf, args.cross_compile)
    symbols = {}
    for line in subprocess.check_output(
            [args.cross_compile + "nm", "-n", str(args.elf)], text=True).splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols[parts[2]] = int(parts[0], 16)
    if symbols["__appended_dtb"] - symbols["_text"] != len(kernel):
        raise ValueError("appended DTB disagrees with ELF symbol")
    start = symbols["__initramfs_start"] - symbols["_text"]
    files = cpio_files(kernel[start:])
    checks = []

    def check(name, present, evidence):
        checks.append(dict(check=name, status="present" if present else "missing",
                           evidence=evidence))

    check("DT clock-provider dependencies", True, clock_evidence)

    # Names cover the selected vendor port, not every possible implementation.
    # Passing says ingredients exist, not that bindings or drivers work.
    for name, symbol in (
        ("CBM driver", "cbm_xrx500_probe"),
        ("Ethernet transmit implementation", "ltq_start_xmit"),
        ("datapath implementation", "dp_xmit"),
        ("GPHY firmware loader", "xrx500_phy_fw_init"),
        ("PCIe host driver", "intel_pcie_probe"),
        ("BCH NAND driver", "grx500_nand_probe"),
        ("native cfg80211", "cfg80211_init"),
        ("native mac80211", "ieee80211_init"),
        ("USB host glue", "grx500_dwc3_probe"),
        ("USB PHY", "grx500_usb_phy_probe"),
        ("MT SMP startup", "vsmp_boot_secondary"),
        ("UBI attachment", "ubi_attach_mtd_dev"),
    ):
        check(name, symbol in symbols,
              {"required_builtin_symbol": symbol,
               "modular_alternatives": "not evaluated by this baseline audit"})
    for name, compatible in (
        ("CBM DT node", ("lantiq,cbm-xrx500",)),
        ("USB host DT node", ("intel,grx500-dwc3",)),
        ("LED DT node", ("gpio-leds",)),
        ("button DT node", ("gpio-keys-polled",)),
        ("calibration NAND DT node", ("tplink,archer-ax3000-v1-nand",)),
        ("Ethernet DT node", ("lantiq,xrx500-eth", "lantiq,xrx500-net")),
        ("PCIe DT node", ("intel,xrx500-pcie", "lantiq,pcie-xrx500")),
        ("GPHY loader DT node", ("lantiq,xrx500-phy-fw", "lantiq,xway-phy-fw", "lantiq,phy-xrx500")),
    ):
        nodes = [path for path in tree.nodes
                 if any(c in tree.compatible(path) for c in compatible)
                 and tree.nodes[path].get("status", b"okay\0") in (b"okay\0", b"ok\0")]
        check(name, bool(nodes), {"enabled_matching_nodes": nodes})
    gphy = "lib/firmware/ltq_fw_PHY11G_IP_xRx5xx_A21.bin"
    check("GPHY payload", bool(files.get(gphy)), {"path": gphy})
    wifi = [p for p in files if p.endswith(("/mtlk.ko", "/mtlk.ko.zst", "/mtlk.ko.gz"))]
    check("WAVE driver", bool(wifi) or "mtlk_hw_mmb_init" in symbols,
          {"modules": wifi, "builtin_symbol": "mtlk_hw_mmb_init"})
    firmware = [p for p in files if "/firmware/" in p and "ap_ram_gen6" in p]
    check("Gen6 radio AP firmware", bool(firmware), {"paths": firmware})
    for label, path in (
        ("calibration preinit loader", "lib/preinit/81_grx500_calibration"),
        ("atomic upgrade implementation", "lib/upgrade/platform.sh"),
        ("factory UBI guard", "usr/sbin/grx500-check-ubi"),
        ("factory MAC loader", "lib/preinit/82_grx500_factory_mac"),
        ("LED configuration", "etc/board.d/01_leds"),
        ("combined WPS/radio button", "etc/rc.wps/00-grx500-combined"),
        ("LED toggle button", "etc/rc.button/lights_toggle"),
        ("regulatory database", "lib/firmware/regulatory.db"),
        ("Wi-Fi configuration tool", "sbin/wifi"),
        ("AP daemon", "usr/sbin/wpad"),
        ("NAND read utility", "usr/sbin/nanddump"),
        ("host-interface radio firmware", "lib/firmware/host_interface_gen6.bin"),
    ):
        check(label, bool(files.get(path)), {"path": path})
    board = "etc/board.d/02_network"
    check("board network setup", bool(files.get(board)), {"path": board})

    if args.directconnect:
        for symbol in ("grx500_umt_probe", "ltq_umt_request", "ltq_umt_set_mode",
                       "grx500_cbm_mmio_phys", "grx500_dma_device", "dc_dp_br_fdb_delete"):
            check("DirectConnect kernel export: " + symbol, symbol in symbols,
                  {"symbol": symbol})
        nodes = [p for p in tree.nodes if "lantiq,mcpy-xrx500" in tree.compatible(p)
                 and tree.nodes[p].get("status", b"okay\0") in (b"okay\0", b"ok\0")]
        check("UMT DT node", bool(nodes), {"nodes": nodes})
        for module_name in ("directconnect_datapath", "dc_mode-hw"):
            paths = [p for p in files if p.endswith(tuple(
                "/" + module_name + suffix for suffix in (".ko", ".ko.gz", ".ko.zst")))]
            check("DirectConnect module: " + module_name, bool(paths), {"paths": paths})
        autoload = files.get("etc/modules.d/60-iwlwav-stock", b"")
        check("DirectConnect software default", b"fastpath=0,0,0" in autoload,
              {"autoload": autoload.decode()})

    return {
        "schema": 1,
        "image": {"path": str(args.image), "sha256": digest(image),
                  "bytes": len(image), "load": hex(h[4]), "entry": hex(h[5])},
        "elf": {"path": str(args.elf), "sha256": digest(args.elf.read_bytes()),
                "matches_image_kernel": True},
        "image_integrity": "passed",
        "kernel_transport": transport,
        "dtb_sha256": digest(dtb), "initramfs_entries": len(files),
        "checks": checks,
        "static_prerequisites_met": all(c["status"] == "present" for c in checks),
        "hardware_tested": False,
        "limitations": [
            "Selected baseline driver names are checked; alternative implementations need manual review.",
            "Presence does not validate driver bindings, reset sequencing, DMA ownership or firmware ABI.",
            "Per-device calibration retrieval, physical flash layout and regulatory configuration remain unverified.",
            "Boot, link, WAN/LAN isolation, both Wi-Fi bands and packet transfer require device tests.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--loader-elf", type=Path)
    parser.add_argument("--cross-compile", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--directconnect", action="store_true",
                        help="also require the optional DirectConnect transport")
    args = parser.parse_args()
    try:
        result = inspect(args)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError,
            lzma.LZMAError, struct.error) as error:
        parser.exit(2, f"unverifiable input: {error}\n")
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    missing = [c["check"] for c in result["checks"] if c["status"] == "missing"]
    print(json.dumps({"report": str(args.output), "missing": missing,
                      "hardware_tested": False}))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
