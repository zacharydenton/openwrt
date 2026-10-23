#!/usr/bin/env python3
"""Expose removal continuing without a completed scan/channel barrier.

Extracts the real synchronous invocation and radio removal functions. Kernel
allocation, request dispatch and queue execution are modeled leaves. By default
an unsafe return fails verification; --expect-vulnerable is only for recording
the known defect, never evidence that the release gate passed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def extract(source, name):
    match = re.search(r'^(?:static\s+)?(?:BOOL|void|int)\s+(?:__MTLK_IFUNC\s+)?' +
                      name + r'\s*\([^;]*?\)\s*\{', source, re.M)
    if not match:
        raise ValueError('missing production function: ' + name)
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tree', type=Path)
    parser.add_argument('--before-patch', type=Path,
                        help='reverse this patch in a disposable copy to reproduce the historical defect')
    parser.add_argument('--expect-vulnerable', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = {name: args.tree / 'wireless/driver/linux' / name
             for name in ('mtlk_df_linux.c', 'wave_radio.c', 'core.c')}
    sources = {name: path.read_text() for name, path in paths.items()}
    if args.before_patch:
        with tempfile.TemporaryDirectory(prefix='ax3000-before-barrier-') as directory:
            root = Path(directory)
            files = ('linux/core.c', 'linux/wave_radio.c', 'linux/mtlk_df_linux.c',
                     'shared/mtlk_serializer.c', 'shared/mtlk_serializer.h',
                     'shared/mtlk_core_iface.h')
            for relative in files:
                source = args.tree / 'wireless/driver' / relative
                target = root / 'wireless/driver' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            subprocess.run(['patch', '--batch', '-R', '-p1', '-i', str(args.before_patch.resolve())],
                           cwd=root, check=True, capture_output=True, text=True)
            sources = {name: (root / 'wireless/driver/linux' / name).read_text() for name in paths}
    invoke = extract(sources['mtlk_df_linux.c'], '_mtlk_df_user_invoke_core')
    radio = '\n'.join(extract(sources['wave_radio.c'], name) for name in
                      ('_wave_radio_abort_and_prevent_scan', 'wave_radio_scan_quiesce'))
    ready = extract(sources['core.c'], 'mtlk_core_ready_to_process_task')
    assert 'RCVRY_TYPE_DUT' in ready and 'RCVRY_TYPE_IGNORE' in ready
    assert 'Failed to allocate execution context object' in sources['core.c']
    assert '_mtlk_abmgr_is_ability_enabled' in sources['core.c']
    harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define MTLK_ERR_OK 0
#define MTLK_ERR_UNKNOWN -1
#define MTLK_ERR_NO_MEM -12
#define MTLK_ERR_NOT_READY -19
#define TRUE 1
#define ELOG_V(...) ((void)0)
#define WAVE_RADIO_REQ_ALTER_SCAN 42
typedef int wave_int;
typedef unsigned mtlk_core_tx_req_id_t;
typedef struct { int live; } mtlk_clpb_t;
typedef struct { int result; } mtlk_user_request_t;
typedef struct { void *vap_handle; } mtlk_df_t;
typedef struct { int abort_scan, pause_or_prevent; } mtlk_alter_scan_t;
typedef struct { int init_done, removed; mtlk_df_t df; } wave_radio_t;
typedef struct { int num_radios; wave_radio_t radio[1]; } wave_radio_descr_t;
static mtlk_clpb_t clipboard;
static int fault, queued_channel, active_scan, dfs_drained, submitted;
static mtlk_clpb_t *mtlk_clpb_create(void) {
  if (fault == 1) return NULL;
  assert(!clipboard.live); clipboard.live=1; return &clipboard;
}
static int mtlk_clpb_push(mtlk_clpb_t *cb, const void *data, size_t size) {
  const mtlk_alter_scan_t *alter=data;
  assert(cb->live && size==sizeof(*alter));
  assert(alter->abort_scan && alter->pause_or_prevent);
  return fault == 2 ? MTLK_ERR_NO_MEM : MTLK_ERR_OK;
}
static void mtlk_clpb_delete(mtlk_clpb_t *cb) { assert(cb->live); cb->live=0; }
static int _mtlk_df_ui_waitable_req_init(mtlk_user_request_t *req) {
  req->result=MTLK_ERR_UNKNOWN; return MTLK_ERR_OK;
}
static void _mtlk_df_ui_req_cleanup(mtlk_user_request_t *req) { (void)req; }
static int _mtlk_df_ui_req_wait_completion(mtlk_user_request_t *req) {
  (void)req; return MTLK_ERR_OK;
}
static int _mtlk_df_ui_req_get_result(mtlk_user_request_t *req) { return req->result; }
static void mtlk_core_handle_tx_ctrl(void *vap, mtlk_user_request_t *req,
                                     unsigned id, mtlk_clpb_t *cb) {
  assert(vap && id==WAVE_RADIO_REQ_ALTER_SCAN && cb->live);
  /* Actual dispatch failure points: allocation before enqueue, recovery
   * readiness before enqueue, and disabled ability after FIFO dispatch. */
  if (fault==3) { req->result=MTLK_ERR_NO_MEM; return; }
  if (fault==4) { req->result=MTLK_ERR_NOT_READY; return; }
  submitted++;
  queued_channel=0;
  if (fault==5) { req->result=MTLK_ERR_NOT_READY; return; }
  active_scan=0;
  req->result=MTLK_ERR_OK;
}
INVOKE
static int _mtlk_df_user_process_core_retval(int result, mtlk_clpb_t *cb,
                                              unsigned id, int cleanup) {
  assert(id==WAVE_RADIO_REQ_ALTER_SCAN && cleanup);
  if (result==MTLK_ERR_OK) mtlk_clpb_delete(cb);
  else assert(!cb);
  return result;
}
static mtlk_df_t *wave_radio_df_get(wave_radio_t *r) { return &r->df; }
static wave_radio_t *wave_radio_scan_support_get(wave_radio_t *r) { return r; }
static void scan_support_prepare_remove(wave_radio_t *r) { r->removed=1; }
static void *mtlk_df_get_user(mtlk_df_t *df) { return df; }
static void mtlk_df_user_quiesce_prop_dfs_wq(void *df) { assert(df); dfs_drained++; }
RADIO
int main(void) {
  for (fault=0; fault<=5; fault++) {
    wave_radio_descr_t radios={.num_radios=1,.radio={{.init_done=1}}};
    radios.radio[0].df.vap_handle=&radios.radio[0];
    queued_channel=active_scan=1; dfs_drained=submitted=0;
    wave_radio_scan_quiesce(&radios);
    assert(radios.radio[0].removed && dfs_drained==1 && !clipboard.live);
    printf("%d %d %d %d\n",fault,queued_channel,active_scan,submitted);
  }
  return 0;
}
'''.replace('\nINVOKE\n', '\n' + invoke + '\n').replace('\nRADIO\n', '\n' + radio + '\n')
    with tempfile.TemporaryDirectory(prefix='ax3000-scan-barrier-failure-') as directory:
        source = Path(directory) / 'probe.c'
        binary = Path(directory) / 'probe'
        source.write_text(harness)
        subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-fno-pie', '-no-pie', str(source), '-o', str(binary)], check=True)
        output = subprocess.run([str(binary)], text=True, capture_output=True, check=True).stdout
    names = ('ordinary', 'clipboard-allocation', 'clipboard-copy-allocation',
             'command-context-allocation', 'recovery-readiness', 'disabled-ability')
    cases = []
    for line in output.splitlines():
        number, channel, scan, submitted = map(int, line.split())
        cases.append(dict(case=names[number], queued_channel_at_return=bool(channel),
                          active_scan_at_return=bool(scan), barrier_submitted=bool(submitted),
                          unsafe_return=bool(channel or scan)))
    assert len(cases)==6 and not cases[0]['unsafe_return']
    vulnerable = all(case['unsafe_return'] for case in cases[1:])
    report = dict(schema=1, hardware_tested=False, release_gate_passed=False,
                  known_failure_reproduced=vulnerable,
                  scope='Actual invocation and radio quiesce functions; modeled allocations, dispatch and pending work. No kernel or firmware execution.',
                  source_sha256={name: hashlib.sha256(source.encode()).hexdigest()
                                 for name, source in sources.items()}, cases=cases)
    if args.before_patch:
        report['reversed_patch_sha256'] = hashlib.sha256(args.before_patch.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if any(case['unsafe_return'] for case in cases):
        print('UNSAFE: removal returned with pending channel work or an active scan')
        if not (args.expect_vulnerable and vulnerable):
            raise SystemExit(1)
        print('Known defect reproduced in five injected failure cases; release gate remains failed')
    elif args.expect_vulnerable:
        raise SystemExit('Expected defect did not reproduce; review the changed implementation')


if __name__ == '__main__':
    main()
