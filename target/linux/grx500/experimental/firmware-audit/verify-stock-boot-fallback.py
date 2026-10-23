#!/usr/bin/env python3
"""Bind the stock U-Boot one-trial bank transition to its exact binary."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

STOCK_UBOOT_SHA256 = '87fae41adc20ac4855d0716917cf4aaebec3c5688102360849fd43475a693f13'
UBOOT_SOURCE_SHA256 = '790ccb12d99fc527a8b8d20dfdf491795d30f87aa0902f8cbda196583aa20bc8'
STOCK_LTQBOOT_SHA256 = '259fb2c096fa5a93315ccedc4c1f218bf2450db0f5932248aefb460526754a07'
BASE = 0xa0400000
CMD_START = 0x53b04
CMD_END = 0x53e1c
CMD_SIZE = 24
SAVEENV_COMMAND_OFFSET = 0x53da4
SAVEENV_FUNCTION = 0xa0413e60
EXPECTED = {
    'check_image0': 'run switchbankA',
    'check_image1': 'run switchbankB;setenv update_chk 0;save',
    'check_image2': 'run switchbankB',
    'check_image3': 'run switchbankA;setenv update_chk 2;save',
}


def sha(data):
    if isinstance(data, Path):
        data = data.read_bytes()
    return hashlib.sha256(data).hexdigest()


def string_at(image, address):
    offset = address - BASE
    if offset < 0 or offset >= len(image):
        raise ValueError('command table pointer outside stock bootloader')
    end = image.find(b'\0', offset)
    if end < 0:
        raise ValueError('unterminated command table string')
    return image[offset:end].decode('ascii')


def commands(image):
    names = []
    entries = {}
    for offset in range(CMD_START, CMD_END, CMD_SIZE):
        words = [int.from_bytes(image[pos:pos + 4], 'big')
                 for pos in range(offset, offset + CMD_SIZE, 4)]
        name = string_at(image, words[0])
        if not re.fullmatch(r'[A-Za-z0-9_?]+', name) or name in entries:
            raise ValueError('unexpected command table entry: ' + name)
        names.append(name)
        entries[name] = {'offset': offset, 'maxargs': words[1],
                         'repeatable': words[2], 'function': words[3],
                         'usage': string_at(image, words[4])}
    if len(names) != 33 or names[0] != 'reset' or names[-1] != 'version':
        raise ValueError('stock command table bounds changed')
    save = entries.get('saveenv')
    if (save is None or save['offset'] != SAVEENV_COMMAND_OFFSET or
            save['maxargs'] != 1 or save['function'] != SAVEENV_FUNCTION or
            save['usage'] != 'save environment variables to persistent storage'):
        raise ValueError('stock saveenv command entry changed')
    # GPL common/command.c find_cmd_tbl accepts a unique abbreviation.
    matches = [name for name in names if name.startswith('save')]
    if matches != ['saveenv']:
        raise ValueError('"save" no longer uniquely resolves to saveenv')
    return names, save


def defaults(image):
    found = {}
    for name, expected in EXPECTED.items():
        prefix = (name + '=').encode()
        offsets = [i for i in range(len(image)) if image.startswith(prefix, i)]
        if len(offsets) != 1:
            raise ValueError(name + ' default not unique')
        end = image.find(b'\0', offsets[0])
        value = image[offsets[0] + len(prefix):end].decode('ascii')
        if value != expected:
            raise ValueError(name + ' default changed')
        found[name] = {'offset': offsets[0], 'value': value}
    return found


def run_default(state, saved, defaults):
    runtime = saved.copy()
    for statement in defaults['check_image' + state]['value'].split(';'):
        parts = statement.split()
        if len(parts) == 2 and parts[0] == 'run' and parts[1] in ('switchbankA', 'switchbankB'):
            runtime['active_bank'] = parts[1][-1]
        elif len(parts) == 3 and parts[:2] == ['setenv', 'update_chk'] and parts[2] in ('0', '2'):
            runtime['update_chk'] = parts[2]
        elif parts == ['save']:
            saved = runtime.copy()
        else:
            raise ValueError('unexpected stock U-Boot statement: ' + statement)
    return runtime, saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bootloader', 'uboot_source', 'stock_ltqboot', 'output'):
        parser.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    args = parser.parse_args()
    for name in vars(args):
        setattr(args, name, getattr(args, name).resolve())
    for path, expected in ((args.bootloader, STOCK_UBOOT_SHA256),
                           (args.uboot_source, UBOOT_SOURCE_SHA256),
                           (args.stock_ltqboot, STOCK_LTQBOOT_SHA256)):
        if sha(path) != expected:
            parser.error('input differs from pinned SHA-256: ' + str(path))
    image = args.bootloader.read_bytes()
    names, save = commands(image)
    choices = defaults(image)
    with tarfile.open(args.uboot_source) as source:
        command_source = source.extractfile('u-boot-2010.06/common/command.c').read().decode()
        env_source = source.extractfile('u-boot-2010.06/common/cmd_nvedit.c').read().decode()
    if not (re.search(r'if\s*\(n_found\s*==\s*1\).*?return cmdtp_temp;',
                      command_source, re.S) and
            'if (strncmp (cmd, cmdtp->name, len) == 0)' in command_source and
            re.search(r'int do_saveenv\s*\([^)]*\).*?return \(saveenv\(\) \? 1 : 0\);',
                      env_source, re.S) and
            re.search(r'U_BOOT_CMD\(\s*saveenv,\s*1,\s*0,\s*do_saveenv,',
                      env_source)):
        raise ValueError('pinned U-Boot source command lookup or save semantics changed')
    ltqboot = args.stock_ltqboot.read_text()
    if not (re.search(r'"\$active_bank" = "B" -a "\$update_chk" = "0".*?--value\s+2',
                      ltqboot, re.S) and
            re.search(r'"\$active_bank" = "A" -a "\$update_chk" != "0".*?--value 0',
                      ltqboot, re.S)):
        raise ValueError('stock Linux bank commit behavior changed')
    cases = []
    for old, new, trial, stable in (('A', 'B', '1', '0'), ('B', 'A', '3', '2')):
        # The stock writer sets both fields before the first reboot.
        saved = {'update_chk': trial, 'active_bank': new}
        first, saved_after_first = run_default(trial, saved, choices)
        second, saved_after_second = run_default(saved_after_first['update_chk'],
                                                 saved_after_first, choices)
        if not (first['active_bank'] == new and first['update_chk'] == stable and
                saved_after_first == first and second['active_bank'] == old and
                second['update_chk'] == stable and
                saved_after_second == saved_after_first):
            raise ValueError('stock two-boot fallback transition failed')
        cases.append({'from_bank': old, 'trial_bank': new, 'initial_update_chk': trial,
                      'first_boot': first, 'saved_after_first_boot': saved_after_first,
                      'second_boot': second, 'saved_after_second_boot': saved_after_second})
    report = {
        'passed': True, 'hardware_tested': False, 'upload_recommended': False,
        'bootloader_sha256': STOCK_UBOOT_SHA256,
        'uboot_source_sha256': UBOOT_SOURCE_SHA256,
        'stock_ltqboot_sha256': STOCK_LTQBOOT_SHA256,
        'command_table_offset': CMD_START, 'command_table_end': CMD_END,
        'command_count': len(names), 'saveenv_command': save,
        'save_abbreviation_matches': [name for name in names if name.startswith('save')],
        'defaults': choices, 'cases': cases,
        'harness_sha256': sha(Path(__file__)),
        'limitations': [
            'This uses official V1-family update bytes, not the user router persistent U-Boot environment.',
            'The GPL command lookup and save implementation are source correspondence, not direct execution of the stock bootloader.',
            'Power cuts, actual NAND environment saves, physical reboot and stock fallback were not tested.',
            'Saved active_bank remains the trial bank after a fallback selection until another save; update_chk controls selection.',
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: stock U-Boot save abbreviation and two-boot bank fallback for both directions')


if __name__ == '__main__':
    main()
