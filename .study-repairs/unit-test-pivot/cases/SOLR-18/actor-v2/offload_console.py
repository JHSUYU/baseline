#!/usr/bin/env python3
"""Offload only noncandidate console logs after node2 SHA verification."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from mirror import DEST, HOST, RECEIPT, ROOT, SSH, digest

HERE = Path(__file__).resolve().parent
STATE = HERE / 'campaign-state.json'
OFFLOAD = HERE / 'console-offload.json'


def eligible(item: dict) -> bool:
    return (not item['effective'] and not item['selected_target_throw']
            and not item['needs_source_review'])


def offload(item: dict) -> bool:
    if not eligible(item):
        return False
    run_id = item['run_id']
    if not re.fullmatch(r'trial-\d{3}', run_id):
        raise ValueError(run_id)
    doc = json.loads(OFFLOAD.read_text()) if OFFLOAD.exists() else {
        'schema_version': 1, 'source_root': str(ROOT),
        'remote_root': HOST + ':' + DEST, 'runs': {}}
    if run_id in doc['runs']:
        return False
    mirror = json.loads(RECEIPT.read_text())
    expected = mirror['runs'][run_id]['sha256']['console.log']
    local = ROOT / run_id / 'console.log'
    if digest(local) != expected:
        raise RuntimeError('local console SHA differs from mirror receipt: ' + run_id)
    remote_path = DEST + '/' + run_id + '/console.log'
    result = subprocess.run(SSH + [HOST, "sha256sum -- '" + remote_path + "'"],
                            capture_output=True, text=True, check=True)
    if result.stdout[:64] != expected:
        raise RuntimeError('remote console SHA differs: ' + run_id)
    local.unlink()
    doc['runs'][run_id] = {
        'offloaded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'reason': 'noncandidate_trial_selected_assertion_not_failed',
        'sha256': expected, 'remote': HOST + ':' + remote_path,
        'local_console_removed': True,
        'local_events_jacoco_run_retained': True}
    temp = OFFLOAD.with_suffix('.json.tmp')
    temp.write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n')
    os.replace(temp, OFFLOAD)
    return True


if __name__ == '__main__':
    state = json.loads(STATE.read_text())
    count = 0
    for item in state['trials']:
        count += offload(item)
    print('offloaded', count, 'noncandidate console logs', flush=True)
