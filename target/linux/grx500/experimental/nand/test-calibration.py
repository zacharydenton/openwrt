#!/usr/bin/env python3
"""Exercise archive validation with GNU tools and an optional host BusyBox.

No NAND access is simulated or claimed: these tests cover the real preinit
archive parser with generated nested gzip/tar containers, including NAND padding.
"""
import argparse
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile


def archive(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.USTAR_FORMAT) as tar:
        for name, data, kind in members:
            entry = tarfile.TarInfo(name)
            if kind == "file":
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
            else:
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/etc/passwd"
                tar.addfile(entry)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--busybox", type=Path)
    args = parser.parse_args()
    script = Path(__file__).resolve().parents[2] / "base-files/lib/preinit/81_grx500_calibration"
    cal0 = ("cal_wlan0.bin", b"A" * 2048, "file")
    cal2 = ("cal_wlan2.bin", b"B" * 2048, "file")
    cases = [
        ("valid", [cal0, cal2], True),
        ("dot-prefix", [("./" + n, d, k) for n, d, k in [cal0, cal2]], True),
        ("missing-radio", [cal0], False),
        ("duplicate", [cal0, cal0, cal2], False),
        ("symlink", [(cal0[0], b"", "link"), cal2], False),
        ("oversize", [(cal0[0], b"A" * 2049, "file"), cal2], False),
        ("undersize", [(cal0[0], b"A" * 255, "file"), cal2], False),
        ("corrupt-inner-crc", [cal0, cal2], False),
        ("duplicate-container", [cal0, cal2], False),
    ]
    with tempfile.TemporaryDirectory(prefix="grx500-cal-test-") as root:
        root = Path(root)
        env = dict(os.environ)
        shell = ["sh"]
        if args.busybox:
            applets = root / "bin"
            applets.mkdir()
            for name in ["gzip", "tar", "awk", "wc"]:
                (applets / name).symlink_to(args.busybox.resolve())
            env["PATH"] = str(applets)
            shell = [str(args.busybox.resolve()), "ash"]
        for label, members, expected in cases:
            work = root / label
            work.mkdir()
            inner = archive(members)
            if label == "corrupt-inner-crc":
                inner = inner[:-8] + bytes([inner[-8] ^ 1]) + inner[-7:]
            outer_members = [("wlanconfig.gz", inner, "file")]
            if label == "duplicate-container":
                outer_members *= 2
            (work / "dump").write_bytes(archive(outer_members) + b"\xff" * 8192)
            command = 'boot_hook_add() { :; }; . "$1"; grx500_calibration_unpack "$2/dump" "$2"'
            result = subprocess.run(shell + ["-c", command, "sh", str(script), str(work)], env=env)
            assert (result.returncode == 0) == expected, (label, result.returncode)
            if expected:
                assert (work / cal0[0]).read_bytes() == cal0[1]
                assert (work / cal2[0]).read_bytes() == cal2[1]
            print(f"PASS {label}")


if __name__ == "__main__":
    main()
