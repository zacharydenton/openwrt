#!/usr/bin/env python3
"""Generate vendor inline logging macros using the bundled logprep tool."""
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
for name in ("loggroups.h", "logmacros.h", "logmacros.c", "driver.scd"):
    (root / name).write_text("")
for path in sorted(root.rglob("*")):
    if path.suffix not in (".c", ".h") or "tools/kconfig/" in str(path):
        continue
    if path.name in ("loggroups.h", "logmacros.h", "logmacros.c"):
        continue
    data = path.read_bytes()
    if not any(word in data for word in (b"ILOG", b"ELOG", b"WLOG", b"SLOG", b"LOG_LOCAL_GID")):
        continue
    result = subprocess.run([
        "perl", str(root / "tools/rtlogger/logprep/logprep.pl"), "gcc", "8", "driver",
        str(root / "loggroups.h"), str(root / "logmacros.h"),
        str(root / "logmacros.c"), str(root / "driver.scd"), "mtlk.o"
    ], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    if result.stdout != data:
        path.write_bytes(result.stdout)
