#!/usr/bin/env python3
"""Send the exact lab factory multipart body through the pinned stock uhttpd.

Both vendor daemons run under QEMU in disposable bubblewrap filesystems. The
only CGI is a compiled host fixture that records request bytes; no stock LuCI
controller, upgrade command, MTD device, or router is exposed to this test.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
UHTTPD_SHA256 = '41368afb8ce60875d8da841dc96158f07a1cc19d666fc7d20e1b909491875fb1'
UBUSD_SHA256 = '7616442b0c7d5c8ca1e18a3491b9bfb19b78661c07edda6a8a69cb1cb42332d3'
QEMU_SHA256 = '8d02f418b92f4ddf984ed8352954b0067d1a5cd810d38247aaf5f0fddc31c42e'
STOCK_SHA256 = '96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b'
BOUNDARY = 'AX3000-STOCK-MULTIPART-3B6E7C1D'
CGI_SOURCE = r'''#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
    char buf[8192];
    ssize_t n;
    int fd = open("/work/captured.bin", O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return 2;
    while ((n = read(STDIN_FILENO, buf, sizeof(buf))) > 0) {
        if (write(fd, buf, n) != n) return 3;
    }
    if (n < 0 || close(fd)) return 4;
    puts("Content-Type: text/plain\r\n\r\nOK");
    return 0;
}
'''


def sha(data):
    if isinstance(data, Path):
        data = data.read_bytes()
    return hashlib.sha256(data).hexdigest()


def multipart(image):
    return (
        ('--' + BOUNDARY + '\r\nContent-Disposition: form-data; name="operation"\r\n'
         '\r\nfirmware\r\n--' + BOUNDARY + '\r\nContent-Disposition: form-data; '
         'name="keep"\r\n\r\non\r\n--' + BOUNDARY + '\r\nContent-Disposition: form-data; '
         'name="image"; filename="UNAPPROVED-factory.bin"\r\n'
         'Content-Type: application/octet-stream\r\n\r\n').encode() + image +
        ('\r\n--' + BOUNDARY + '--\r\n').encode()
    )


def wait_for_socket(path, process):
    for _ in range(100):
        if path.exists():
            return
        if process.poll() is not None:
            raise RuntimeError('stock ubusd exited before creating its socket')
        time.sleep(.05)
    raise RuntimeError('stock ubusd did not create its socket')


def wait_for_port(port, process):
    for _ in range(100):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                return
        except OSError:
            if process.poll() is not None:
                raise RuntimeError('stock uhttpd exited before listening')
            time.sleep(.05)
    raise RuntimeError('stock uhttpd did not listen')


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('rootfs', 'stock', 'qemu', 'factory', 'route_report', 'output', 'artifacts'):
        parser.add_argument('--' + name.replace('_', '-'), required=True, type=Path)
    args = parser.parse_args()
    for name in vars(args):
        setattr(args, name, getattr(args, name).resolve())
    for program in ('bwrap', 'gcc', 'curl'):
        if not shutil.which(program):
            parser.error(program + ' is required')
    pinned = {
        args.rootfs / 'usr/sbin/uhttpd': UHTTPD_SHA256,
        args.rootfs / 'sbin/ubusd': UBUSD_SHA256,
        args.qemu: QEMU_SHA256,
        args.stock: STOCK_SHA256,
    }
    for path, expected in pinned.items():
        if sha(path) != expected:
            parser.error('input differs from pinned SHA-256: ' + str(path))
    route = json.loads(args.route_report.read_text())
    image = args.factory.read_bytes()
    body = multipart(image)
    if not (route['passed'] and route['candidate_sha256'] == sha(image) and
            route['multipart_sha256'] == sha(body) and
            route['multipart_bytes'] == len(body)):
        parser.error('multipart request differs from the passed stock LuCI route test')
    if len(body) > 32 * 1024 * 1024:
        parser.error('multipart body exceeds the stock LuCI default upload size')
    args.artifacts.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='stock-uhttpd-ingress-') as temp:
        work = Path(temp)
        (work / 'www/cgi-bin').mkdir(parents=True)
        (work / 'run').mkdir()
        shutil.copytree(args.rootfs / 'etc/config', work / 'config')
        (work / 'config/sysmode').write_text("config sysmode 'sysmode'\n\toption mode 'router'\n")
        (work / 'capture.c').write_text(CGI_SOURCE)
        (work / 'multipart.bin').write_bytes(body)
        with (args.artifacts / 'compiler.log').open('wb') as log:
            subprocess.run(['gcc', '-static', '-O2', '-o', str(work / 'www/cgi-bin/capture'),
                            str(work / 'capture.c')], stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=30)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        command = ['bwrap', '--unshare-all', '--share-net', '--die-with-parent',
                   '--new-session', '--cap-drop', 'ALL', '--clearenv', '--setenv',
                   'PATH', '/bin:/sbin:/usr/bin:/usr/sbin', '--tmpfs', '/']
        for name in ('bin', 'sbin', 'lib', 'usr', 'etc'):
            command += ['--ro-bind', str(args.rootfs / name), '/' + name]
        command += ['--ro-bind', str(work / 'config'), '/etc/config',
                    '--ro-bind', str(args.qemu), '/qemu', '--proc', '/proc',
                    '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/var',
                    '--bind', str(work / 'run'), '/var/run', '--bind', str(work), '/work']
        with (args.artifacts / 'ubusd.log').open('wb') as ubus_log, \
             (args.artifacts / 'uhttpd.log').open('wb') as http_log:
            ubusd = subprocess.Popen(command + ['/qemu', '/sbin/ubusd'],
                                     stdout=ubus_log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            server = None
            try:
                wait_for_socket(work / 'run/ubus.sock', ubusd)
                server = subprocess.Popen(
                    command + ['/qemu', '/usr/sbin/uhttpd', '-f', '-p',
                               '127.0.0.1:' + str(port), '-h', '/work/www',
                               '-x', '/cgi-bin', '-t', '120', '-T', '30', '-n', '3',
                               '-R', '-A', '1', '-r', 'OpenWrt'],
                    stdout=http_log, stderr=subprocess.STDOUT,
                    start_new_session=True)
                wait_for_port(port, server)
                for name, expect in (('browser-style', False), ('expect-continue', True)):
                    captured = work / 'captured.bin'
                    captured.unlink(missing_ok=True)
                    response = args.artifacts / (name + '-response.txt')
                    curl = ['curl', '--noproxy', '*', '--max-time', '60', '--silent',
                            '--show-error', '--output', str(response), '--write-out',
                            '%{http_code}', '--header',
                            'Content-Type: multipart/form-data; boundary=' + BOUNDARY,
                            '--header', 'Expect: 100-continue' if expect else 'Expect:',
                            '--data-binary', '@' + str(work / 'multipart.bin'),
                            'http://127.0.0.1:' + str(port) + '/cgi-bin/capture']
                    request = subprocess.run(curl, capture_output=True, text=True,
                                             timeout=65)
                    result = {
                        'mode': name, 'curl_exit_code': request.returncode,
                        'http_status': request.stdout, 'curl_stderr': request.stderr,
                        'response_sha256': sha(response) if response.exists() else None,
                        'captured_bytes': captured.stat().st_size if captured.exists() else None,
                        'captured_sha256': sha(captured) if captured.exists() else None,
                    }
                    result['passed'] = (request.returncode == 0 and
                                        request.stdout == '200' and
                                        response.read_bytes() == b'OK\n' and
                                        result['captured_bytes'] == len(body) and
                                        result['captured_sha256'] == sha(body))
                    results.append(result)
            finally:
                if server is not None:
                    stop(server)
                stop(ubusd)
    report = {
        'passed': all(result['passed'] for result in results) and len(results) == 2,
        'hardware_tested': False, 'upload_recommended': False,
        'stock_uhttpd_executed': True, 'stock_ubusd_executed': True,
        'stock_uhttpd_sha256': UHTTPD_SHA256, 'stock_ubusd_sha256': UBUSD_SHA256,
        'stock_firmware_sha256': STOCK_SHA256, 'qemu_sha256': QEMU_SHA256,
        'factory_sha256': sha(image), 'multipart_bytes': len(body),
        'multipart_sha256': sha(body), 'route_report_sha256': sha(args.route_report),
        'harness_sha256': sha(Path(__file__)), 'cgi_source_sha256': sha(CGI_SOURCE.encode()),
        'results': results,
        'limitations': [
            'A synthetic CGI captured the request; stock LuCI authentication and dispatch were not reached over HTTP.',
            'The stock daemons ran in emulated userspace with a generated sysmode config and temporary ubus socket.',
            'No physical router upload, flash write, boot, Ethernet, Wi-Fi, or fallback was tested.',
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if not report['passed']:
        raise SystemExit('FAIL: stock uhttpd did not preserve the exact multipart request')
    print('PASS: stock uhttpd accepted and preserved', len(body),
          'multipart bytes in both HTTP request modes')


if __name__ == '__main__':
    main()
