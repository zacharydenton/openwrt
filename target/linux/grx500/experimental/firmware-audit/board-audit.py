#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read GRX500 firmware DTBs; preserve raw evidence and derive board resources.

This is an offline decoder, not a hardware or firmware-boot test. No firmware
code is executed. Python's standard library is the only dependency.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def cells(data):
    if len(data) % 4:
        raise ValueError("cell property is not a multiple of four bytes")
    return list(struct.unpack(">" + "I" * (len(data) // 4), data))


def number(data):
    return int.from_bytes(data, "big")


def strings(data):
    if not data or not data.endswith(b"\0"):
        raise ValueError("invalid string property")
    return data[:-1].decode("ascii").split("\0")


def parent(path):
    return path.rsplit("/", 1)[0] or "/"


class Tree:
    def __init__(self, path):
        self.data = path if isinstance(path, bytes) else Path(path).read_bytes()
        if len(self.data) < 40:
            raise ValueError("truncated DTB header")
        magic, total, off, so, _, version, _, _, slen, length = struct.unpack(
            ">10I", self.data[:40])
        if magic != 0xd00dfeed or version < 17 or total != len(self.data):
            raise ValueError("expected a complete version-17 or newer DTB")
        if off + length > total or so + slen > total:
            raise ValueError("DTB block exceeds input")
        self.nodes = {}
        self.locations = {}
        names = self.data[so:so+slen]
        stack = []
        end = off + length
        while off + 4 <= end:
            token = number(self.data[off:off+4])
            off += 4
            if token == 1:
                nul = self.data.index(b"\0", off, end)
                name = self.data[off:nul].decode("ascii")
                path = (stack[-1].rstrip("/") + "/" + name) if stack else "/"
                if path in self.nodes:
                    raise ValueError("duplicate node")
                stack.append(path)
                self.nodes[path] = {}
                self.locations[path] = {}
                off = (nul + 4) & ~3
            elif token == 2:
                stack.pop()
            elif token == 3:
                size, noff = struct.unpack(">II", self.data[off:off+8])
                off += 8
                if off + size > end or not stack or noff >= len(names):
                    raise ValueError("invalid property")
                key = names[noff:names.index(b"\0", noff)].decode("ascii")
                if key in self.nodes[stack[-1]]:
                    raise ValueError("duplicate property")
                self.nodes[stack[-1]][key] = self.data[off:off+size]
                self.locations[stack[-1]][key] = off
                off = (off + size + 3) & ~3
            elif token == 4:
                continue
            elif token == 9:
                if stack:
                    raise ValueError("unclosed node")
                break
            else:
                raise ValueError(f"invalid DTB token {token}")
        else:
            raise ValueError("missing end token")
        self.phandles = {}
        for path, props in self.nodes.items():
            if "phandle" in props:
                phandle = number(props["phandle"])
                if phandle in self.phandles:
                    raise ValueError("duplicate phandle")
                self.phandles[phandle] = path

    def uint(self, path, key, default=None):
        data = self.nodes[path].get(key)
        if data is None:
            return default
        if len(data) != 4:
            raise ValueError(f"expected u32: {path}:{key}")
        return number(data)

    def compatible(self, path):
        return strings(self.nodes[path]["compatible"]) if "compatible" in self.nodes[path] else []

    def matching(self, compatible):
        return [p for p in self.nodes if compatible in self.compatible(p)]

    def translate(self, bus, address, size):
        """Translate simple-bus addresses to CPU physical addresses.

        Missing ranges is deliberately an error; it does not mean identity.
        PCI ranges are decoded separately, not passed as simple addresses here.
        """
        while bus != "/":
            p = parent(bus)
            ranges = self.nodes[bus].get("ranges")
            if ranges is None:
                raise ValueError(f"no address translation at {bus}")
            if ranges:
                ac = self.uint(bus, "#address-cells", 2)
                pac = self.uint(p, "#address-cells", 2)
                sc = self.uint(bus, "#size-cells", 1)
                stride = 4 * (ac + pac + sc)
                if len(ranges) % stride:
                    raise ValueError("bad ranges length")
                for i in range(0, len(ranges), stride):
                    child = number(ranges[i:i+4*ac])
                    start = number(ranges[i+4*ac:i+4*(ac+pac)])
                    extent = number(ranges[i+4*(ac+pac):i+stride])
                    if child <= address and address + size <= child + extent:
                        address = start + address - child
                        break
                else:
                    raise ValueError(f"address outside ranges at {bus}")
            bus = p
        return address

    def registers(self, path):
        bus = parent(path)
        ac = self.uint(bus, "#address-cells", 2)
        sc = self.uint(bus, "#size-cells", 1)
        stride = 4 * (ac + sc)
        data = self.nodes[path].get("reg", b"")
        names = strings(self.nodes[path]["reg-names"]) if "reg-names" in self.nodes[path] else []
        if len(data) % stride:
            raise ValueError(f"bad reg length: {path}")
        result = []
        for i in range(0, len(data), stride):
            address = number(data[i:i+4*ac])
            size = number(data[i+4*ac:i+stride])
            result.append({"index": i // stride, "name": names[i//stride] if names else None,
                           "bus_address": hex(address), "size": hex(size),
                           "cpu_physical_address": hex(self.translate(bus, address, size))})
        return result

    def irqs(self, path):
        props = self.nodes[path]
        values = cells(props.get("interrupts", b""))
        if not values:
            return None
        q = path
        while "interrupt-parent" not in self.nodes[q] and q != "/":
            q = parent(q)
        ph = self.uint(q, "interrupt-parent")
        controller = self.phandles.get(ph)
        result = {"raw_cells": values, "controller": controller}
        if controller and "lantiq,gic-grx500" in self.compatible(controller):
            # Vendor irq.c installs an identity legacy domain beginning at 8;
            # gic_init uses MIPS_GIC_IRQ_BASE == MIPS_CPU_IRQ_BASE + 8.
            if self.uint(controller, "#interrupt-cells") != 1 or any(v < 8 for v in values):
                raise ValueError("unexpected vendor GIC interrupt format")
            result["derived_modern_GIC_SHARED_indices"] = [v - 8 for v in values]
        return result

    def evidence(self, path):
        """No heuristic string decoding: zero cells remain unambiguous bytes."""
        return {k: {"dtb_offset": hex(self.locations[path][k]), "hex": v.hex()}
                for k, v in self.nodes[path].items()}


def identity(path):
    data = Path(path).read_bytes()
    return {"file": Path(path).name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def parse_dtb(data):
    """Return a Tree with raw bytes in .nodes and typed decoding methods."""
    return Tree(data)


def manifest(tree, args):
    output = {"schema": 1, "evidence_type": "static DTB bytes and packaged/source configuration",
              "stock_dtb": identity(args.stock_dtb), "model": strings(tree.nodes["/"]["model"]),
              "limitations": ["No boot, physical port, PCI enumeration, or packet transfer observed.",
                              "Embedded reference DTB can be modified or superseded by the bootloader.",
                              "A status=ok PCIe controller does not prove an attached radio or its silicon revision.",
                              "Modern GIC indices are derived from the vendor legacy domain; interrupt trigger types are not encoded by its one-cell binding."],
              "pcie": [], "ethernet": [], "cbm": [], "gpio": [], "switches": [],
              "supporting_files": {}, "raw_nodes": {}}
    selected = {"/", "/aliases", "/chosen", "/memory@0"}
    for path in tree.matching("lantiq,pcie-xrx500"):
        p = tree.nodes[path]
        gpio = cells(p["reset-gpio"])
        gp = tree.phandles[gpio[0]]
        reset = cells(p["resets"])
        item = {"path": path, "registers": tree.registers(path), "interrupts": tree.irqs(path),
                "reset": {"controller": gp, "bank": tree.uint(gp, "lantiq,bank"),
                          "line": gpio[1], "raw_gpio_flags": gpio[2],
                          "active_level": "high" if tree.uint(path, "lantiq,rst-high-active") else "low",
                          "interval_ms": tree.uint(path, "lantiq,rst-interval"),
                          "phy_reset_controller": tree.phandles[reset[0]], "phy_reset_bit": reset[1]},
                "settings": {key: tree.uint(path, "lantiq," + key) for key in
                             ("phy-mode", "clkout", "inbound-shift", "outbound-shift", "inbound-swap", "outbound-swap")},
                "ranges": []}
        r = cells(p["ranges"])
        if tree.uint(path, "#address-cells") != 3 or tree.uint(path, "#size-cells") != 2 or len(r) % 6:
            raise ValueError("unexpected PCI ranges format")
        for i in range(0, len(r), 6):
            flags, hi, lo, pa, sh, sl = r[i:i+6]
            size = (sh << 32) | sl
            item["ranges"].append({"flags": hex(flags), "pci_bus_address": hex((hi << 32) | lo),
                                   "parent_bus_address": hex(pa), "size": hex(size),
                                   "cpu_physical_address": hex(tree.translate(parent(path), pa, size))})
        imap = cells(p["interrupt-map"])
        if len(imap) % 6:
            raise ValueError("unexpected PCI interrupt-map")
        item["intx"] = [{"pin": imap[i+3], "raw_irq": imap[i+5],
                         "derived_modern_GIC_SHARED_index": imap[i+5] - 8}
                        for i in range(0, len(imap), 6)]
        output["pcie"].append(item)
        selected.update((path, parent(path), gp, tree.phandles[reset[0]]))
    for path in tree.matching("lantiq,xrx500-pdi-port"):
        ph = tree.uint(path, "phy-handle")
        phy = tree.phandles.get(ph)
        output["ethernet"].append({"path": path, "dt_port_number": tree.uint(path, "reg"),
                                   "wan": "lantiq,wan" in tree.nodes[parent(path)],
                                   "phy": phy, "mdio_address": tree.uint(phy, "reg") if phy else None,
                                   "interrupts": tree.irqs(path)})
        selected.update((path, parent(path), parent(parent(path))))
        if phy:
            selected.update((phy, parent(phy)))
    for path in tree.matching("lantiq,cbm-xrx500"):
        queues = {p: dict(zip(("tmu_port", "tmu_queue", "dma_controller", "dma_channel", "port_enable", "descriptors"),
                             cells(props["lantiq,cbm-config"])))
                  for p, props in tree.nodes.items() if p.startswith(path + "/") and "lantiq,cbm-config" in props}
        output["cbm"].append({"path": path, "registers": tree.registers(path),
                              "interrupts": tree.irqs(path), "queue_configuration": queues})
        selected.update(queues)
        selected.add(path)
    for compatible, key in (("lantiq,gpio-xrx500", "gpio"), ("lantiq,xrx500-gswapi", "switches")):
        for path in tree.matching(compatible):
            output[key].append({"path": path, "registers": tree.registers(path), "interrupts": tree.irqs(path)})
            selected.add(path)
    output["memory"] = tree.registers("/memory@0")
    selected.update(tree.matching("lantiq,gic-grx500"))
    selected.update(tree.matching("lantiq,xway-phy-fw"))
    selected.update(tree.matching("lantiq,phy-xrx500"))
    for path in list(selected):
        while path != "/":
            path = parent(path)
            selected.add(path)
    output["raw_nodes"] = {path: tree.evidence(path) for path in sorted(selected) if path in tree.nodes}
    if args.rootfs:
        for relative in ("lib/switch/core_phy.sh", "etc/preinit.d/load_gphy_firmware_preinit.sh", "etc/init.d/switch", "etc/init.d/phyport"):
            path = args.rootfs / relative
            output["supporting_files"][relative] = identity(path)
        script = (args.rootfs / "lib/switch/core_phy.sh").read_text()
        def values(name):
            match = re.search(r'^' + re.escape(name) + r'="([^"]+)"$', script, re.M)
            if not match:
                raise ValueError(f"missing stock variable {name}")
            return match[1].split()
        output["stock_script_ports"] = {"lan_interfaces_in_label_order": values("LAN_IFNAMES"),
                                         "lan_switch_ports_in_label_order": [int(x) for x in values("LAN_PORTS")],
                                         "wan_interface": values("WAN_IFNAME"),
                                         "wan_switch_ports": [int(x) for x in values("WAN_PORTS")]}
    if args.sdk_config:
        output["supporting_files"]["product-sdk.config"] = identity(args.sdk_config)
        config = args.sdk_config.read_text().splitlines()
        keys = ("CONFIG_UBOOT_CONFIG_DDR_256M=", "CONFIG_UBOOT_CONFIG_MEM=", "CONFIG_UBOOT_CONFIG_PHYM=", "CONFIG_UBOOT_CONFIG_ADDMISC=")
        output["product_memory_config"] = [{"line": i+1, "text": line} for i, line in enumerate(config) if line.startswith(keys)]
    if args.openwrt_dtb:
        other = Tree(args.openwrt_dtb)
        groups = {"cbm": ["lantiq,cbm-xrx500"], "ethernet": ["lantiq,xrx500-net", "lantiq,xrx500-eth"],
                  "pcie": ["lantiq,pcie-xrx500", "intel,xrx500-pcie"],
                  "gpio": ["lantiq,gpio-xrx500", "intel,grx500-gpio"],
                  "gphy_loader": ["lantiq,xway-phy-fw", "lantiq,phy-xrx500", "intel,xrx500-phy-fw"]}
        output["openwrt_comparison"] = {"dtb": identity(args.openwrt_dtb),
            "compatible_nodes": {key: sorted({p for c in cs for p in other.matching(c)}) for key, cs in groups.items()},
            "memory": {p: other.registers(p) for p in other.nodes if other.nodes[p].get("device_type") == b"memory\0"},
            "scope": "Exact compatible-name inventory, not exhaustive driver binding or functionality validation."}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_dtb", type=Path)
    parser.add_argument("--rootfs", type=Path)
    parser.add_argument("--sdk-config", type=Path)
    parser.add_argument("--openwrt-dtb", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = manifest(Tree(args.stock_dtb), args)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {args.output}: {len(result['pcie'])} PCIe controllers, {len(result['ethernet'])} Ethernet DT ports; no hardware validation performed")


if __name__ == "__main__":
    main()
