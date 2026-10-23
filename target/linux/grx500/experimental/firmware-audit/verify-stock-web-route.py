#!/usr/bin/env python3
"""Run the pinned stock LuCI multipart route on exact laboratory image bytes.

The stock HTTP parser, controller and fmup bytecode run in isolated MIPS
userspace. External commands are stubs; no HTTP server or flash is run.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
STOCK_SHA256 = '96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b'
PINNED = {
    'usr/bin/lua': 'e63e3a6ee64769d2c74085f692a93f0cfa793660efbafdb5f617d1277e61c9f0',
    'usr/lib/lua/luci/controller/admin/firmware.lua':
        'd52bddc4cb7946f86f151740068245f4269b6c4145031a02544baf6b4051f59a',
    'usr/lib/lua/luci/model/fmup.lua':
        '81ac85c424a31c38ef8dbd715f993842b07eade97122600cef56eeaa7bd85a02',
    'usr/lib/lua/luci/util.lua':
        'edb2f35ad7d5e2ff68a449e0ae07350a4e210636a050081387d5be2640546ded',
    'usr/lib/lua/luci/ltn12.lua':
        'c6a24c93f5a6817850a18c7f92904ca0dfab720bca7f7b22ba724708a96dccb5',
    'usr/lib/lua/luci/http.lua':
        '43d5fb551112d64119b08c8f84e3fc6cca46ce415e59d8aa26638e2c13185088',
    'usr/lib/lua/luci/http/protocol.lua':
        'b3451af4a30048efc1635420d8c099cb5cfa35f1a42d38c9ea664b53c4b88d71',
    'www/webpages/pages/userrpm/firmwareUpgrade.1693532644203.html':
        '66e6f9cde3aeb60a3f6c4da6b9cef0d02dee5438309f16888bd3fd818dd57be8',
}
QEMU_SHA256 = '8d02f418b92f4ddf984ed8352954b0067d1a5cd810d38247aaf5f0fddc31c42e'
DEFAULT_UPLOAD_LIMIT = 33554432 + 2048 + 4096 + 16 + 4
BOUNDARY = 'AX3000-STOCK-MULTIPART-3B6E7C1D'
COMMANDS = ('CHECK nvrammanager -c "/tmp/firmware.bin"\n'
            'WRITE nvrammanager -u "/tmp/firmware.bin"\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('rootfs', 'stock', 'qemu', 'factory', 'writer_report', 'output', 'artifacts'):
        parser.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    args = parser.parse_args()
    for name in vars(args):
        setattr(args, name, getattr(args, name).resolve())
    if not shutil.which('bwrap'):
        parser.error('bubblewrap is required; no unisolated fallback')
    if sha(args.stock) != STOCK_SHA256 or sha(args.qemu) != QEMU_SHA256:
        parser.error('stock firmware or QEMU differs from the pinned inputs')
    for name, expected in PINNED.items():
        if sha(args.rootfs / name) != expected:
            parser.error('stock rootfs file differs from the pinned input: ' + name)
    page = (args.rootfs / 'www/webpages/pages/userrpm/firmwareUpgrade.1693532644203.html').read_text()
    if not (re.search(r'<input\b[^>]*\bname="image"[^>]*\btype="file"', page) and
            re.search(r'<input\b[^>]*\bname="keep"[^>]*\bvalue="on"', page) and
            re.search(r'extension:\s*"bin"', page) and
            re.search(r'operation:\s*"firmware"', page)):
        parser.error('stock web form fields or .bin selector changed')
    writer_report = json.loads(args.writer_report.read_text())
    candidate_hash = sha(args.factory)
    exact_cases = [case for case in writer_report.get('cases', [])
                   if case.get('case') in ('exact-factory-checker', 'exact-factory-writer')]
    if not (writer_report.get('passed') is True and len(exact_cases) == 2 and
            {case['case'] for case in exact_cases} ==
            {'exact-factory-checker', 'exact-factory-writer'} and
            all(case.get('passed') is True and
                case.get('input_sha256') == candidate_hash for case in exact_cases)):
        parser.error('candidate is not the exact stock checker/writer-tested container')
    candidate = args.factory.read_bytes()
    if BOUNDARY.encode() in candidate:
        parser.error('multipart boundary occurs inside candidate')
    multipart = (
        ('--' + BOUNDARY + '\r\nContent-Disposition: form-data; name="operation"\r\n'
         '\r\nfirmware\r\n--' + BOUNDARY + '\r\nContent-Disposition: form-data; '
         'name="keep"\r\n\r\non\r\n--' + BOUNDARY + '\r\nContent-Disposition: form-data; '
         'name="image"; filename="UNAPPROVED-factory.bin"\r\n'
         'Content-Type: application/octet-stream\r\n\r\n').encode() +
        candidate + ('\r\n--' + BOUNDARY + '--\r\n').encode())
    if args.factory.suffix != '.bin' or len(multipart) > DEFAULT_UPLOAD_LIMIT:
        parser.error('candidate does not fit the stock default web form/handler limit')

    args.artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stock-web-route-') as tmp:
        work = Path(tmp)
        shutil.copy2(args.factory, work / 'input.bin')
        (work / 'multipart.bin').write_bytes(multipart)
        shutil.copy2(HERE / 'stock-web-route.lua', work / 'upload.lua')
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
                   '--cap-drop', 'ALL', '--clearenv', '--setenv', 'PATH',
                   '/bin:/sbin:/usr/bin:/usr/sbin', '--tmpfs', '/']
        for name in ('bin', 'sbin', 'lib', 'usr', 'etc'):
            command += ['--ro-bind', str(args.rootfs / name), '/' + name]
        command += ['--ro-bind', str(args.qemu), '/qemu', '--proc', '/proc',
                    '--dev', '/dev', '--tmpfs', '/tmp', '--symlink', 'tmp', '/var',
                    '--bind', str(work), '/work', '--chdir', '/work',
                    '/qemu', '/usr/bin/lua', '/work/upload.lua']
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        (args.artifacts / 'stdout.log').write_text(result.stdout)
        (args.artifacts / 'stderr.log').write_text(result.stderr)
        commands = (work / 'commands.txt').read_text() if (work / 'commands.txt').exists() else ''
        (args.artifacts / 'commands.txt').write_text(commands)
        rejected = ((work / 'rejected-commands.txt').read_text()
                    if (work / 'rejected-commands.txt').exists() else '')
        (args.artifacts / 'rejected-commands.txt').write_text(rejected)
        checker_rejection_blocked_writer = (
            rejected.startswith('CHECK nvrammanager -c "/tmp/firmware.bin"\n') and
            'WRITE nvrammanager -u' not in rejected)
        captured = work / 'captured.bin'
        captured_hash = sha(captured) if captured.exists() else None
        captured_bytes = captured.stat().st_size if captured.exists() else None
        passed = (result.returncode == 0 and captured_hash == candidate_hash and
                  captured_bytes == args.factory.stat().st_size and commands == COMMANDS and
                  checker_rejection_blocked_writer and
                  f'CAPTURE_BYTES\t{captured_bytes}\tSTOCK_ROUTE_COMMANDS\t2' in result.stdout)
        report = {
            'passed': passed, 'hardware_tested': False,
            'http_request_performed': False, 'flash_operations_performed': False,
            'stock_lua_multipart_parser_executed': True,
            'stock_sha256': STOCK_SHA256, 'stock_rootfs_sha256': PINNED,
            'stock_lua_interpreter_sha256': PINNED['usr/bin/lua'],
            'qemu_sha256': QEMU_SHA256, 'fixture_sha256': sha(HERE / 'stock-web-route.lua'),
            'harness_sha256': sha(__file__), 'candidate_sha256': candidate_hash,
            'candidate_bytes': args.factory.stat().st_size,
            'multipart_bytes': len(multipart),
            'multipart_sha256': hashlib.sha256(multipart).hexdigest(),
            'multipart_fields': ['operation', 'keep', 'image'],
            'stock_default_upload_limit_bytes': DEFAULT_UPLOAD_LIMIT,
            'captured_sha256': captured_hash, 'captured_bytes': captured_bytes,
            'checker_writer_report_sha256': sha(args.writer_report),
            'external_commands_intercepted': commands.splitlines(),
            'checker_rejection_writer_blocked': checker_rejection_blocked_writer,
            'rejection_commands_intercepted': rejected.splitlines(),
            'exit_code': result.returncode,
            'stdout_sha256': sha(args.artifacts / 'stdout.log'),
            'stderr_sha256': sha(args.artifacts / 'stderr.log'),
            'scope': ('Genuine stock LuCI HTTP multipart parser, request object, '
                      'controller, fmup and util bytecode ran under isolated MIPS QEMU. '
                      'The browser-form fields delivered the exact container and reached '
                      'checker then writer dispatch.'),
            'limitations': [
                'The HTTP server, authentication and actual network request were not run.',
                'The UCI upload-size profile was stubbed to its bytecode default; a user device may override it.',
                'External checker/writer commands were intercepted here and tested separately; no flash ran.',
                'No router boot, Ethernet, Wi-Fi or stock fallback was tested.',
            ],
        }
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        if not passed:
            raise SystemExit('FAIL: stock web route did not preserve or dispatch exact candidate')
        print('PASS: stock Lua web route preserved', captured_bytes,
              'bytes and dispatched checker before writer')


if __name__ == '__main__':
    main()
