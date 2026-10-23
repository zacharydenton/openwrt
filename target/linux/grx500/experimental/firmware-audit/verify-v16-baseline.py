#!/usr/bin/env python3
"""Bind a fresh V1.60-page download to the firmware used for this port."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ZIP_SHA256 = '6198caa78034f69a029b1e4009c2a69f4c36ea9e673e75338b50925543198846'
PAYLOAD_SHA256 = '96a9a7a6bd82ea5340a70181c687136eeeba3320c46e923b00ac9acfabcbc10b'
PAYLOAD_NAME = 'ax3000v1_intel-up-ver1-0-6-P1[20230831-rel67466]_sign.bin'
OFFICIAL_URL = ('https://static.tp-link.com/upload/firmware/2023/202309/20230906/'
                'Archer%20AX3000%28US%29_V1_230831.zip')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v16-zip', type=Path, required=True)
    parser.add_argument('--pinned-zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fresh = args.v16_zip.read_bytes()
    pinned = args.pinned_zip.read_bytes()
    if fresh != pinned or sha(fresh) != ZIP_SHA256:
        raise ValueError('V1.60 download differs from the pinned V1 archive')
    with zipfile.ZipFile(args.v16_zip) as archive:
        payload = archive.read(PAYLOAD_NAME)
        if sha(payload) != PAYLOAD_SHA256:
            raise ValueError('firmware payload differs from the pinned update')
    report = {
        'schema': 1,
        'v16_support_page': 'https://www.tp-link.com/us/support/download/archer-ax3000/v1.60/',
        'official_download_url': OFFICIAL_URL,
        'zip_sha256': ZIP_SHA256,
        'payload_name': PAYLOAD_NAME,
        'payload_sha256': PAYLOAD_SHA256,
        'fresh_matches_pinned': True,
        'router_firmware_version_observed': False,
        'hardware_tested': False,
    }
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: V1.60-page firmware matches pinned V1 230831 archive and payload')


if __name__ == '__main__':
    main()
