#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Apply the experimental Ethernet port to a disposable prepared kernel tree."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True,
                        help="Intel Linux checkout at the manifest's commit")
    parser.add_argument("--kernel", type=Path, required=True,
                        help="disposable copy of the prepared GRX500 kernel")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    vendor, kernel = args.vendor.resolve(), args.kernel.resolve()
    manifest = json.loads((here / "ethernet-sources.json").read_text())
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=vendor, text=True).strip()
    if head != manifest["commit"]:
        parser.error(f"vendor HEAD must be {manifest['commit']}, got {head}")
    if "CONFIG_INTEL_MIPS=y\n" not in (kernel / ".config").read_text():
        parser.error("kernel must be configured for the GRX500 target")
    if (kernel / "drivers/net/ethernet/lantiq/grx500-soc.c").exists():
        parser.error("experiment already applied; use a fresh kernel copy")
    for entry in manifest["files"]:
        dst = kernel / entry["destination"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(vendor / entry["source"], dst)
    run("patch", "--batch", "--forward", "-p1", "-i",
        str(here / "ethernet-linux-6.18.patch"), cwd=kernel)
    shutil.copyfile(here / "Kconfig.ethernet",
                    kernel / "arch/mips/intel-mips/Kconfig.ethernet")
    hooks = {
        "arch/mips/intel-mips/Kconfig":
            'source "arch/mips/intel-mips/Kconfig.ethernet"',
        "drivers/net/ethernet/Makefile": "obj-$(CONFIG_INTEL_MIPS) += lantiq/",
        "drivers/net/Makefile": "obj-$(CONFIG_INTEL_MIPS) += datapath/",
        "drivers/dma/Makefile": "obj-$(CONFIG_INTEL_MIPS) += intel/",
    }
    for name, line in hooks.items():
        with (kernel / name).open("a") as out:
            out.write("\n" + line + "\n")
    (kernel / "drivers/net/datapath/Makefile").write_text("obj-y += dpm/\n")
    # Diagnostic build only: retain warnings from the legacy vendor sources.
    run(str(kernel / "scripts/config"), "--file", str(kernel / ".config"),
        "--disable", "WERROR", "--enable", "DMADEVICES", "--enable", "PCI")
    print("Prepared experimental sources. Run olddefconfig and vmlinux with "
          "the OpenWrt MIPS toolchain. This does not produce router firmware.")


if __name__ == "__main__":
    main()
