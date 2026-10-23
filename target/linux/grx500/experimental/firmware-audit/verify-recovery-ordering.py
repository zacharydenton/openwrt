#!/usr/bin/env python3
"""Bind the target's weak-ordering setting to a compiled wireless IRQ fence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-config', type=Path, required=True)
p.add_argument('--module', type=Path, required=True)
p.add_argument('--cross-compile', required=True)
p.add_argument('--stock-config', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

assert 'CONFIG_WEAK_ORDERING=y' in a.stock_config.read_text().splitlines()
assert 'CONFIG_WEAK_ORDERING=y' in a.kernel_config.read_text().splitlines(), 'SMP barriers still assume strong ordering'
assert 'CONFIG_SMP=y' in a.kernel_config.read_text().splitlines()
function = 'mtlk_hw_mmb_interrupt_handler_msi'
disassembly = subprocess.check_output([a.cross_compile + 'objdump', '-dr',
    '--disassemble=' + function, str(a.module)], text=True)
assert '<' + function + '>:' in disassembly
instructions = re.findall(r'^\s*[0-9a-f]+:\s+[0-9a-f]+\s+([^\n]+)', disassembly, re.M)
calls = [i for i, line in enumerate(instructions) if line.startswith('jalr')]
assert len(calls) == 1, 'Unexpected IRQ-dispatch shape; inspect manually'
call = calls[0]
fences = [i for i, line in enumerate(instructions[:call]) if re.match(r'sync(?:\s|$)', line)]
assert fences and any(line.startswith('lw') for line in instructions[:fences[-1]]), 'Missing acquire fence before ISR dispatch'
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.with_suffix('.disassembly').write_text(disassembly)
result = dict(passed=True, hardware_tested=False, upload_recommended=False,
    stock_config_sha256=sha(a.stock_config), kernel_config_sha256=sha(a.kernel_config),
    module_sha256=sha(a.module), function=function,
    disassembly_sha256=sha(a.output.with_suffix('.disassembly')),
    verifier_sha256=sha(Path(__file__)),
    scope='Current SMP config enables weak ordering, matching stock; emitted MSI dispatcher has a sync fence between loads and indirect ISR call. No hardware execution.')
a.output.write_text(json.dumps(result, indent=2) + '\n')
print('PASS: weak-ordering SMP config and compiled MSI acquire fence')
