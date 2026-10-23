#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check that the factory image was built from the port's runtime sources."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOTS = (
    "package/firmware/ax3000-stock-firmware",
    "package/kernel/iwlwav-stock",
    "package/utils/grx500-factory",
    "target/linux/grx500",
)
AUDIT = "target/linux/grx500/experimental/firmware-audit/"
CONFIG = "target/linux/grx500/config-6.18"
FACTORY_PACKAGE = "CONFIG_PACKAGE_grx500-factory-install=y"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def files(root):
    found = {}
    for directory in ROOTS:
        for path in (root / directory).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc", ".rst"):
                continue
            name = str(path.relative_to(root))
            if "/tests/" in name:
                continue
            if name.startswith(AUDIT) and not (
                name == AUDIT + "build-relocated-kernel.py" or
                name.startswith(AUDIT + "relocated-kernel.")
            ):
                continue
            found[name] = path
    return found


def commit(root):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "factory", "image", "image-report", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    source, factory = args.source.resolve(), args.factory.resolve()
    expected, actual = files(source), files(factory)
    if expected.keys() != actual.keys():
        raise ValueError("source paths differ: " + repr({
            "source_only": sorted(expected.keys() - actual.keys()),
            "factory_only": sorted(actual.keys() - expected.keys()),
        }))

    matched = {}
    overrides = {}
    for name in sorted(expected):
        left, right = expected[name].read_bytes(), actual[name].read_bytes()
        if name == CONFIG:
            if left.count(b"# CONFIG_GRX500_FACTORY_TRIAL is not set") != 1:
                raise ValueError("unexpected development kernel flag")
            adjusted = left.replace(b"# CONFIG_GRX500_FACTORY_TRIAL is not set",
                                    b"CONFIG_GRX500_FACTORY_TRIAL=y")
            if adjusted != right:
                raise ValueError("factory kernel configuration differs unexpectedly")
            overrides[name] = dict(source_sha256=sha(left), factory_sha256=sha(right),
                                   only_change="CONFIG_GRX500_FACTORY_TRIAL=y")
        elif left != right:
            raise ValueError("build input differs: " + name)
        else:
            matched[name] = sha(left)

    source_config = set((source / ".config").read_text().splitlines())
    factory_config = set((factory / ".config").read_text().splitlines())
    # defconfig writes an explicit disabled entry in the development build.
    # Treat that as equivalent to the older absent entry, while still
    # requiring the factory build to select the install marker.
    source_config.discard("# CONFIG_PACKAGE_grx500-factory-install is not set")
    if source_config - factory_config or factory_config - source_config != {FACTORY_PACKAGE}:
        raise ValueError("package selection differs beyond the factory install marker")
    if commit(source) != commit(factory):
        raise ValueError("OpenWrt base commits differ")

    image_report = json.loads(args.image_report.read_text())
    if image_report["image_sha256"] != sha(args.image.read_bytes()) or not image_report["checks_passed"]:
        raise ValueError("factory image is not bound to a passing image audit")
    digest = sha("".join(name + " " + value + "\n" for name, value in matched.items()).encode())
    report = dict(passed=True, hardware_tested=False, upload_recommended=False,
                  source_commit=commit(source), factory_commit=commit(factory),
                  identical_build_input_count=len(matched),
                  identical_build_inputs_sha256=digest,
                  factory_kernel_config_override=overrides,
                  factory_extra_package=FACTORY_PACKAGE,
                  verified_factory_sysupgrade_sha256=image_report["image_sha256"],
                  scope="Target, Ethernet, Wi-Fi, package and relocation-loader build inputs match the source except the explicit factory kernel flag and install-marker package.",
                  limitation="Source parity and a successful build do not establish hardware operation or stock recovery.")
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {len(matched)} matching factory build inputs")


if __name__ == "__main__":
    main()
