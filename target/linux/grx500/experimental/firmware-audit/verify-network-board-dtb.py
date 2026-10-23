#!/usr/bin/env python3
"""Compare the built AX3000 DTB's network wiring with pinned stock evidence."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('board_audit', here / 'board-audit.py')
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)

STOCK_DTB_SHA256 = '98872195bcc1e16f8f56b6f21eecee4335dc6c9a788f1c224014432ede48c198'
STOCK_SWITCH_SHA256 = 'dbc647bfe8c5c2184e00f827522a7a379aa98e19811701d0200a6f785f6f6267'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(stock, current, switch_text):
    checks = []

    def same(name, got, expected):
        if got != expected:
            raise ValueError(f'{name}: built {got!r}, stock-derived {expected!r}')
        checks.append(name)

    def regpair(tree, path, index=0):
        reg = tree.registers(path)[index]
        return int(reg['cpu_physical_address'], 16), int(reg['size'], 16)

    def ints(tree, path, key):
        return board.cells(tree.nodes[path][key])

    stock_pcie = sorted(stock.matching('lantiq,pcie-xrx500'), key=lambda p: regpair(stock, p)[0])
    current_pcie = sorted(current.matching('intel,xrx500-pcie'), key=lambda p: regpair(current, p)[0])
    same('PCIe controller count', len(current_pcie), len(stock_pcie))
    same('PCIe controller count is three', len(current_pcie), 3)
    for sp, cp in zip(stock_pcie, current_pcie):
        name = f'PCIe {hex(regpair(stock, sp)[0])}'
        sr = stock.registers(sp)
        cr = current.registers(cp)
        for index, label in enumerate(('csr', 'cfg', 'app')):
            same(f'{name} {label} MMIO', regpair(current, cp, index), regpair(stock, sp, index))
            same(f'{name} {label} name', cr[index]['name'], sr[index]['name'])
        phy_addr, phy_size = regpair(stock, sp, 3)
        phy = f'/phy@{phy_addr:x}'
        same(f'{name} PHY MMIO', regpair(current, phy), (phy_addr, phy_size))
        old_gpio = ints(stock, sp, 'reset-gpio')
        old_gpio_path = stock.phandles[old_gpio[0]]
        bank = stock.uint(old_gpio_path, 'lantiq,bank')
        old_high = stock.uint(sp, 'lantiq,rst-high-active')
        new_gpio = ints(current, cp, 'reset-gpios')
        new_gpio_path = current.phandles[new_gpio[0]]
        same(f'{name} reset bank MMIO', regpair(current, new_gpio_path)[0], 0x16c00000 + bank * 0x100)
        same(f'{name} reset GPIO', new_gpio[1:], [old_gpio[1], 0 if old_high else 1])
        old_reset = ints(stock, sp, 'resets')
        new_reset = ints(current, phy, 'resets')
        same(f'{name} PHY reset offset/bit', new_reset[1:], [0x10, old_reset[1]])
        for old, new in (('lantiq,inbound-shift', 'intel,inbound-shift'),
                         ('lantiq,outbound-shift', 'intel,outbound-shift'),
                         ('lantiq,inbound-swap', 'intel,inbound-swap'),
                         ('lantiq,outbound-swap', 'intel,outbound-swap'),
                         ('lantiq,rst-interval', 'intel,rst-interval')):
            same(f'{name} {new}', current.uint(cp, new), stock.uint(sp, old))
        same(f'{name} fixed-window iATU', current.uint(cp, 'intel,iatu'), 0)
        same(f'{name} stock PHY mode', stock.uint(sp, 'lantiq,phy-mode'), 5)
        same(f'{name} SSC enable', current.uint(phy, 'intel,ssc-enable'), 1)
        old_ir = ints(stock, sp, 'interrupts')[-1] - 8
        new_ir = ints(current, cp, 'interrupts')
        same(f'{name} integrated IRQ', new_ir, [0, old_ir, 4])
        old_map, new_map = ints(stock, sp, 'interrupt-map'), ints(current, cp, 'interrupt-map')
        same(f'{name} INTx entry count', len(new_map) // 8, len(old_map) // 6)
        for pin in range(4):
            old = old_map[pin*6:(pin+1)*6]
            new = new_map[pin*8:(pin+1)*8]
            same(f'{name} INTx {pin+1}', [new[3], new[5], new[6], new[7]],
                 [old[3], 0, old[5] - 8, 4])
        old_range = ints(stock, sp, 'ranges')[:6]
        new_range = ints(current, cp, 'ranges')
        cpu_base = stock.translate(board.parent(sp), old_range[3], old_range[5])
        same(f'{name} PCI MEM CPU/BAR window', new_range,
             [old_range[0], 0, cpu_base, cpu_base, 0, old_range[5]])

    old_cbm = stock.matching('lantiq,cbm-xrx500')
    new_cbm = current.matching('lantiq,cbm-xrx500')
    same('CBM node count', len(new_cbm), len(old_cbm))
    same('CBM MMIO banks', [regpair(current, new_cbm[0], i) for i in range(12)],
         [regpair(stock, old_cbm[0], i) for i in range(12)])
    same('CBM IRQs', ints(current, new_cbm[0], 'interrupts'),
         [item for irq in ints(stock, old_cbm[0], 'interrupts') for item in (0, irq - 8, 4)])

    stock_dma0 = stock.matching('lantiq,dma0-grx500')
    current_dma0 = current.matching('lantiq,dma0-grx500')
    same('DMA0 node count', len(current_dma0), len(stock_dma0))
    sp, cp = stock_dma0[0], current_dma0[0]
    same('DMA0 MMIO', regpair(current, cp), regpair(stock, sp))
    same('DMA0 IRQ', ints(current, cp, 'interrupts'),
         [0, ints(stock, sp, 'interrupts')[0] - 8, 4])
    same('DMA0 stock alias', board.strings(stock.nodes['/aliases']['dma0']), [sp])
    same('DMA0 alias', board.strings(current.nodes['/aliases']['dma0']), [cp])
    for key in ('lantiq,desc-num', 'lantiq,dma-burst', 'lantiq,dma-polling-cnt',
                'lantiq,dma-drb', 'lantiq,budget'):
        same(f'DMA0 {key}', current.uint(cp, key), stock.uint(sp, key))
    clocks = ints(current, cp, 'clocks')
    same('DMA0 clock binding', [current.phandles[clocks[0]], clocks[1]],
         ['/clock-controller@16200000', 107])

    stock_dma = {regpair(stock, path)[0]: path for path in stock.matching('lantiq,dma-grx500')}
    current_dma = {regpair(current, path)[0]: path for path in current.matching('lantiq,dma-grx500')}
    # DMA3 is the stock TOE/memory-copy engine; DMA4 must stay disabled.
    for alias, base in enumerate((0x1a100000, 0x1a200000, 0x1c100000,
                                  0x1c200000, 0x1e300000, 0x1e400000), 1):
        sp, cp = stock_dma[base], current_dma[base]
        name = f'DMA{alias} {base:#x}'
        same(f'{name} MMIO', regpair(current, cp), regpair(stock, sp))
        same(f'{name} IRQ', ints(current, cp, 'interrupts'),
             [0, ints(stock, sp, 'interrupts')[0] - 8, 4])
        same(f'{name} stock alias', board.strings(stock.nodes['/aliases'][f'dma{alias}']), [sp])
        same(f'{name} alias', board.strings(current.nodes['/aliases'][f'dma{alias}']), [cp])
        same(f'{name} status',
             board.strings(current.nodes[cp]['status']) if 'status' in current.nodes[cp] else ['okay'],
             board.strings(stock.nodes[sp]['status']) if 'status' in stock.nodes[sp] else ['okay'])
        for key in ('lantiq,dma-pkt-arb', 'lantiq,dma-burst', 'lantiq,dma-polling-cnt',
                    'lantiq,dma-chan-fc', 'lantiq,dma-desc-fod',
                    'lantiq,dma-desc-in-sram', 'lantiq,dma-drb',
                    'lantiq,dma-byte-en', 'lantiq,dma-lab-cnt', 'lantiq,budget'):
            if key in stock.nodes[sp]:
                same(f'{name} {key}', current.uint(cp, key), stock.uint(sp, key))
        if base == 0x1e300000:
            clocks = ints(current, cp, 'clocks')
            same(f'{name} TOE clock binding',
                 [current.phandles[clocks[0]], clocks[1]],
                 ['/clock-controller@16200000', 120])

    for base in (0x1c000000, 0x1a000000):
        old_switch = [p for p in stock.matching('lantiq,xrx500-gswapi') if regpair(stock, p)[0] == base]
        new_switch = [p for p in current.matching('intel,gswdev') if regpair(current, p)[0] == base]
        same(f'switch {base:#x} node count', len(new_switch), len(old_switch))
        same(f'switch {base:#x} MMIO', regpair(current, new_switch[0]), regpair(stock, old_switch[0]))

    def var(name):
        m = re.search(r'^' + name + r'="([^"]+)"$', switch_text, re.M)
        if not m:
            raise ValueError(f'missing stock switch variable {name}')
        return m.group(1).split()

    lan_ports = [int(x) for x in var('LAN_PORTS')]
    wan_ports = [int(x) for x in var('WAN_PORTS')]
    same('four stock LAN port labels', len(lan_ports), 4)
    same('one stock WAN port label', len(wan_ports), 1)
    expected = {f'lan{i+1}': (port, port, False) for i, port in enumerate(lan_ports)}
    expected['wan'] = (wan_ports[0], 1, True)
    old_phy = {}
    for path in stock.matching('lantiq,xrx500-pdi-port'):
        props = stock.nodes[path]
        if 'phy-handle' not in props:
            continue
        phy = stock.phandles[stock.uint(path, 'phy-handle')]
        old_phy[(stock.uint(path, 'reg'), 'lantiq,wan' in stock.nodes[board.parent(path)])] = stock.uint(phy, 'reg')
    found = {}
    for path in current.matching('lantiq,xrx500-pdi'):
        props = current.nodes[path]
        if 'label' not in props:
            raise ValueError(f'{path}: missing netdev label')
        label = board.strings(props['label'])[0]
        if label in found:
            raise ValueError(f'duplicate netdev label {label}')
        found[label] = path
    same('LAN/WAN netdev labels', set(found), set(expected))
    for label, (dp_port, phy_port, wan) in expected.items():
        path = found[label]
        same(f'{label} datapath port', [current.uint(path, 'intel,dp-dev-port'),
                                      current.uint(path, 'intel,dp-port-id')], [dp_port, dp_port])
        same(f'{label} switch port', current.uint(path, 'reg'), dp_port)
        same(f'{label} WAN flag', current.uint(path, 'lantiq,wan', 0), 1 if wan else 0)
        children = [p for p in current.matching('lantiq,xrx500-pdi-port') if board.parent(p) == path]
        same(f'{label} PHY child count', len(children), 1)
        child = children[0]
        same(f'{label} PHY switch port', current.uint(child, 'reg'), phy_port)
        phy = current.phandles[current.uint(child, 'phy-handle')]
        same(f'{label} PHY MDIO address', current.uint(phy, 'reg'), old_phy[(phy_port, wan)])
        same(f'{label} PHY mode', board.strings(current.nodes[child]['phy-mode']), ['rgmii'])

    old_gphy = stock.matching('lantiq,phy-xrx500')
    new_gphy = current.matching('lantiq,phy-xrx500')
    same('GPHY loader count', len(new_gphy), len(old_gphy))
    old_resets = ints(stock, old_gphy[0], 'resets')
    new_resets = ints(current, new_gphy[0], 'resets')
    same('five GPHY reset bits', [new_resets[i] for i in range(2, len(new_resets), 3)],
         [old_resets[i] for i in range(1, len(old_resets), 2)])
    same('GPHY reset offsets', [new_resets[i] for i in range(1, len(new_resets), 3)], [0x10]*5)
    same('board Linux RAM', regpair(current, '/memory@20000000'), (0x20000000, 0x0e000000))
    return checks


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stock-dtb', type=Path, required=True)
    p.add_argument('--openwrt-dtb', type=Path, required=True)
    p.add_argument('--stock-switch-script', type=Path, required=True)
    p.add_argument('--initramfs-report', type=Path)
    p.add_argument('--sysupgrade-report', type=Path)
    p.add_argument('--negative-controls', action='store_true',
                   help='mutate eight DTB properties and require the wiring check to reject each')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if sha(a.stock_dtb) != STOCK_DTB_SHA256 or sha(a.stock_switch_script) != STOCK_SWITCH_SHA256:
        raise ValueError('stock DTB/switch script differs from pinned AX3000(US) 230831 evidence')
    current_sha = sha(a.openwrt_dtb)
    compiled_gates = {}
    for name, report in (('initramfs', a.initramfs_report), ('sysupgrade', a.sysupgrade_report)):
        if not report:
            continue
        image_report = json.loads(report.read_text())
        if image_report['dtb_sha256'] != current_sha:
            raise ValueError(f'{name} image report binds a different DTB')
        clocks = image_report.get('clock_provider')
        if clocks is None:
            clocks = next((check['evidence'] for check in image_report['checks']
                           if check['check'] == 'DT clock-provider dependencies'), None)
        if not clocks or clocks['compiled_branch_table']['status'] != 'pass':
            raise ValueError(f'{name} image lacks a compiled clock-table audit')
        compiled_gates[name] = {}
        for gate_name, gate_id, bit in (('GCLK_DMA0', 107, 5), ('GCLK_TOE', 120, 22)):
            gate = clocks['required_gates'].get(gate_name)
            if not gate or gate['id'] != gate_id or gate['bit'] != bit:
                raise ValueError(f'{name} image lacks compiled {gate_name} gate')
            compiled_gates[name][gate_name] = gate
    stock = board.Tree(a.stock_dtb)
    current = board.Tree(a.openwrt_dtb)
    switch_text = a.stock_switch_script.read_text()
    checks = verify(stock, current, switch_text)
    rejected = []
    if a.negative_controls:
        alternate_phy = current.uint('/ethernet/interface@4/ethernet@4', 'phy-handle')
        mutations = (
            ('PCIe2 reset GPIO', '/pcie@18e00000', 'reset-gpios', 1, 7),
            ('CBM IRQ', '/cbm@1e700000', 'interrupts', 1, 175),
            ('DMA1TX descriptor SRAM', '/dma@1a100000', 'lantiq,dma-desc-in-sram', 0, 0),
            ('DMA0 gate clock', '/dma@16e00000', 'clocks', 1, 120),
            ('DMA3 TOE clock', '/dma@1e300000', 'clocks', 1, 107),
            ('LAN1 PHY phandle', '/ethernet/interface@5/ethernet@5', 'phy-handle', 0, alternate_phy),
            ('PCIe0 MEM window', '/pcie@18900000', 'ranges', 2, 0xb8001000),
            ('Linux RAM span', '/memory@20000000', 'reg', 1, 0x10000000),
        )
        for name, path, key, cell, value in mutations:
            data = bytearray(current.data)
            offset = current.locations[path][key] + 4 * cell
            data[offset:offset+4] = value.to_bytes(4, 'big')
            try:
                verify(stock, board.Tree(bytes(data)), switch_text)
            except ValueError as exc:
                rejected.append({'name': name, 'reason': str(exc)})
            else:
                raise AssertionError(f'negative control accepted: {name}')
    result = {'schema': 1, 'stock_dtb_sha256': STOCK_DTB_SHA256,
              'stock_switch_script_sha256': STOCK_SWITCH_SHA256,
              'openwrt_dtb_sha256': current_sha,
              'images_bound': {'initramfs': bool(a.initramfs_report),
                               'sysupgrade': bool(a.sysupgrade_report)},
              'compiled_dma_clock_gates': compiled_gates,
              'checks': checks, 'check_count': len(checks),
              'negative_controls_rejected': rejected,
              'hardware_tested': False,
              'scope': 'Static DTB wiring comparison; no PCI enumeration, link, RF or Ethernet traffic. TOE/memory-copy runtime remains untested.'}
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS: {len(checks)} stock-derived built-DTB wiring checks; '
          f'{len(rejected)} negative controls rejected')


if __name__ == '__main__':
    main()
