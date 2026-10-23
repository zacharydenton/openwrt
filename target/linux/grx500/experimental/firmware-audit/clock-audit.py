#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check compiled DT clock references against the actual GRX500 provider.

This establishes static registration and register consistency, not hardware
clock operation. audit_clocks(dtb, target) can be called by the image auditor.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess


def uncomment(source):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)


def definitions(source):
    return {name: int(value, 0) for name, value in re.findall(
        r"^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|[0-9]+)\s*$",
        uncomment(source), re.M)}


def audit_clocks(dtb, target, provider_text=None):
    """Return JSON-compatible evidence; raise ValueError on missing resources."""
    target = Path(target)
    provider_path = target / "files/drivers/clk/intel/clk-grx500.c"
    source = provider_path.read_text() if provider_text is None else provider_text
    clean = uncomment(source)
    binding = target / "files/include/dt-bindings/clock/intel,grx500-clk.h"
    ids = definitions(binding.read_text())
    registers = definitions(source)
    registered_names = re.findall(r"\bINTEL_\w+\s*\(\s*([A-Z][A-Z0-9_]+)\s*,", clean)
    if len(registered_names) != len(set(registered_names)):
        raise ValueError("duplicate clock registration")
    registered = {ids[name]: name for name in registered_names}
    if len(registered) != len(registered_names):
        raise ValueError("duplicate registered clock ID")

    # These are independently corroborated by the TP-Link 3.10 sysctrl.c:
    # CGU_CLK_SR1=0x120, CR1_A=0x124, CR1_B=0x128 and BIT(n) masks.
    required = {"GCLK_DMA0": 5, "GCLK_CBM": 9, "GCLK_EBU": 10,
                "GCLK_TOE": 22, "GCLK_PAE": 26,
                "GCLK_USB1": 27, "GCLK_GSWIP": 28}
    gates = {}
    for args in re.findall(r"\bINTEL_GATE\s*\(([^)]+)\)", clean):
        fields = [arg.strip() for arg in args.split(",")]
        name = fields[0]
        if name in required:
            if len(fields) != 8 or fields[6] != "GATE_CLK_HW":
                raise ValueError(f"{name}: expected hardware gate semantics")
            reg, bit = registers[fields[4]], registers[fields[5]]
            if reg != 0x120 or bit != required[name]:
                raise ValueError(f"{name}: wrong status register or bit")
            gates[name] = {"id": ids[name], "status": reg, "enable": reg + 4,
                           "disable": reg + 8, "bit": bit}
    if set(gates) != set(required):
        raise ValueError("missing mandatory gates: " + ", ".join(sorted(set(required) - set(gates))))

    common = (target / "files/drivers/clk/intel/clk-cgu.c").read_text()
    for macro, expression in {"STAT": r"\(reg\)", "EN": r"\(\(reg\)\s*\+\s*0x4\)",
                              "DIS": r"\(\(reg\)\s*\+\s*0x8\)"}.items():
        if not re.search(r"#define\s+GATE_HW_REG_" + macro + r"\(reg\)\s+" + expression, common):
            raise ValueError("unexpected hardware gate register offsets")

    spec = importlib.util.spec_from_file_location("grx500_board_audit", Path(__file__).with_name("board-audit.py"))
    board = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(board)
    tree = board.parse_dtb(dtb)
    references = []
    for node, props in tree.nodes.items():
        if "clocks" not in props:
            continue
        cells = board.cells(props["clocks"])
        offset = 0
        while offset < len(cells):
            phandle = cells[offset]
            offset += 1
            if phandle == 0:
                continue
            if phandle not in tree.phandles:
                raise ValueError(f"{node}: unresolved clock provider {phandle}")
            clock_node = tree.phandles[phandle]
            clock_props = tree.nodes[clock_node]
            count = tree.uint(clock_node, "#clock-cells")
            if count is None or offset + count > len(cells):
                raise ValueError(f"{node}: invalid clock specifier")
            if b"intel,grx500-cgu" in clock_props.get("compatible", b"").split(b"\0"):
                if count != 1 or cells[offset] not in registered:
                    raise ValueError(f"{node}: unregistered CGU clock {cells[offset:offset+count]}")
                references.append({"consumer": node, "provider": clock_node,
                                   "id": cells[offset], "name": registered[cells[offset]]})
            offset += count
    if not references:
        raise ValueError("no GRX500 CGU consumers found")
    return {"status": "pass", "dtb_sha256": hashlib.sha256(dtb).hexdigest(),
            "provider_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "registered_ids": sorted(registered), "required_gates": gates,
            "references": references}


def audit_compiled_clocks(evidence, kernel, elf, cross_compile):
    """Check clock records inside the already byte-bound MIPS o32 kernel.

    intel_clk_branch has 84-byte records with id/type at 0/4 and the gate
    register/shift/flags at 60/64/68 in this target ABI. Do not silently apply
    these offsets to a different architecture or a changed driver structure.
    """
    symbols = {}
    for line in subprocess.check_output(
            [cross_compile + 'nm', '-S', str(elf)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 4:
            symbols[fields[3]] = (int(fields[0], 16), int(fields[1], 16))
        elif len(fields) == 3:
            symbols[fields[2]] = (int(fields[0], 16), 0)
    address, size = symbols['grx500_branch_clks']
    offset = address - symbols['_text'][0]
    if size % 84 or offset < 0 or offset + size > len(kernel):
        raise ValueError('unexpected compiled clock branch table layout')
    records = {}
    for start in range(offset, offset + size, 84):
        entry = kernel[start:start + 84]
        ident, kind = struct.unpack_from('>II', entry)
        if ident in records:
            raise ValueError('duplicate compiled clock ID')
        records[ident] = (kind, struct.unpack_from('>I', entry, 60)[0],
                          entry[64], struct.unpack_from('>I', entry, 68)[0])
    for reference in evidence['references']:
        if reference['id'] not in records:
            raise ValueError('DT clock absent from compiled branch table: ' + reference['name'])
    for name, gate in evidence['required_gates'].items():
        if records.get(gate['id']) != (4, gate['status'], gate['bit'], 1 << 17):
            raise ValueError('wrong or absent compiled hardware gate: ' + name)
    evidence['compiled_branch_table'] = {
        'address': hex(address), 'bytes': size,
        'sha256': hashlib.sha256(kernel[offset:offset + size]).hexdigest(),
        'registered_ids': sorted(records), 'status': 'pass'}
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("--target", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        result = audit_clocks(args.dtb.read_bytes(), args.target)
    except (ValueError, KeyError) as error:
        parser.exit(1, f"clock audit failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
