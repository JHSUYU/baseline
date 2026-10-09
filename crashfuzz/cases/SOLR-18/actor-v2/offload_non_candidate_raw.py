#!/usr/bin/env python3
"""Move completed noncandidate event/JaCoCo copies off node0 after node2 SHA checks."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import subprocess

from mirror import DEST, HOST, NODE2_LOCAL, RECEIPT, ROOT, SSH, digest
from offload_console import eligible

HERE = Path(__file__).resolve().parent
STATE = HERE / 'campaign-state.json'
OFFLOAD = HERE / 'noncandidate-raw-offload.json'
NAMES = ('events.tsv', 'jacoco.exec')


def offload(item: dict) -> bool:
    if NODE2_LOCAL:
        return False
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
    mirror = json.loads(RECEIPT.read_text())['runs'][run_id]
    assert mirror['rsync_checksum_dry_run_exit'] == 0
    assert mirror['rsync_checksum_dry_run_output'] == ''
    expected = {name: mirror['sha256'][name] for name in NAMES}
    directory = ROOT / run_id
    for name in NAMES:
        if digest(directory / name) != expected[name]:
            raise RuntimeError('local SHA differs from mirror receipt: ' + run_id + '/' + name)
    remote_dir = DEST + '/' + run_id
    command = "sha256sum -- " + ' '.join("'" + remote_dir + '/' + name + "'" for name in NAMES)
    output = subprocess.run(SSH + [HOST, command], capture_output=True,
                            text=True, check=True).stdout.splitlines()
    remote = {Path(line[66:]).name: line[:64] for line in output}
    if remote != expected:
        raise RuntimeError('node2 SHA differs from mirror receipt: ' + run_id)
    removed_bytes = sum((directory / name).stat().st_size for name in NAMES)
    for name in NAMES:
        (directory / name).unlink()
    doc['runs'][run_id] = {
        'offloaded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'reason': 'completed_noncandidate_trial',
        'sha256': expected, 'remote_directory': HOST + ':' + remote_dir,
        'local_raw_bytes_removed': removed_bytes,
        'local_plan_run_and_target_receipts_retained': True}
    temp = OFFLOAD.with_suffix('.json.tmp')
    temp.write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n')
    os.replace(temp, OFFLOAD)
    return True


if __name__ == '__main__':
    state = json.loads(STATE.read_text())
    count = sum(offload(item) for item in state['trials'])
    print('offloaded', count, 'noncandidate event and JaCoCo pairs', flush=True)
