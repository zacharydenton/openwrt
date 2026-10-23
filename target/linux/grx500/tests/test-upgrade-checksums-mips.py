#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the real upgrade checksum shell with packaged MIPS BusyBox applets."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile


BASE = Path(__file__).resolve().parents[1]
PLATFORM = BASE / "base-files/lib/upgrade/platform.sh"
MEMBER_PREFIX = "sysupgrade-tplink_archer-ax3000-v1/"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("qemu", "root", "image", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ("qemu", "root", "image", "output"):
        setattr(args, name, getattr(args, name).resolve())

    harness = "\n".join((
        ". " + shlex.quote(str(PLATFORM)),
        'tar() { "$QEMU" -L "$TARGET_ROOT" "$TARGET_ROOT/bin/busybox" tar "$@"; }',
        'sha256sum() { "$QEMU" -L "$TARGET_ROOT" "$TARGET_ROOT/bin/busybox" sha256sum "$@"; }',
        'awk() { "$QEMU" -L "$TARGET_ROOT" "$TARGET_ROOT/bin/busybox" awk "$@"; }',
        'grx500_upgrade_checksums "$1"',
        "",
    ))
    with tempfile.TemporaryDirectory(prefix="ax3000-mips-checksums-") as tmp:
        tmp = Path(tmp)
        script = tmp / "check.sh"
        script.write_text(harness)
        original = args.image.read_bytes()
        with tarfile.open(args.image) as archive:
            offsets = {}
            for name in ("kernel", "root"):
                member = archive.getmember(MEMBER_PREFIX + name)
                if member.size < 129:
                    raise ValueError("member too small: " + name)
                offsets[name] = member.offset_data + 128

        results = []
        for name in ("intact", "kernel-corrupt", "root-corrupt"):
            data = bytearray(original)
            if name != "intact":
                data[offsets[name.split("-")[0]]] ^= 1
            candidate = tmp / (name + ".tar")
            candidate.write_bytes(data)
            env = dict(os.environ, QEMU=str(args.qemu), TARGET_ROOT=str(args.root))
            process = subprocess.run(
                [str(args.qemu), "-L", str(args.root),
                 str(args.root / "bin/busybox"), "sh", str(script), str(candidate)],
                env=env, text=True, capture_output=True, timeout=30,
            )
            passed = (process.returncode == 0 if name == "intact" else
                      process.returncode != 0 and
                      "AX3000 sysupgrade payload checksum mismatch." in process.stderr)
            results.append(dict(case=name, passed=passed,
                                candidate_sha256=hashlib.sha256(data).hexdigest(),
                                exit_code=process.returncode,
                                stderr=process.stderr.strip()))

    report = dict(passed=all(item["passed"] for item in results),
                  hardware_tested=False, flash_operations_performed=False,
                  image_sha256=sha(args.image),
                  packaged_mips_busybox_sha256=sha(args.root / "bin/busybox"),
                  qemu_sha256=sha(args.qemu), platform_source_sha256=sha(PLATFORM),
                  cases=results)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if not report["passed"]:
        raise SystemExit("MIPS checksum cases failed")
    print("PASS: packaged MIPS shell accepts intact image and rejects both corrupt payloads")


if __name__ == "__main__":
    main()
