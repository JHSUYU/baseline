#!/usr/bin/env python3
"""Run two independent healthy original JUnits under one distinct Lucene seed."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from run_native import RUN_ROOT, run


HERE = Path(__file__).resolve().parent
SEED = 'A94D53B5E2C7F601'
RUN_IDS = ('healthy-v3-seed2-a', 'healthy-v3-seed2-b')
MIN_FREE_BYTES = 10 * 1024**3 + 256 * 1024**2
STATE = HERE / 'seed2-calibration-state.json'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(value: dict) -> None:
    temp = STATE.with_suffix('.json.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, STATE)


def resource_guard() -> dict:
    stat = os.statvfs(RUN_ROOT)
    free = stat.f_bavail * stat.f_frsize
    rows = subprocess.run(['jps', '-l'], capture_output=True, text=True,
                          check=True).stdout.splitlines()
    business = [row for row in rows if 'sun.tools.jps.Jps' not in row]
    assert free >= MIN_FREE_BYTES, (free, MIN_FREE_BYTES)
    assert len(business) <= 4, business
    assert not any('research.solr18.OriginalJUnit' in row for row in business), business
    return {'free_bytes': free, 'business_jvms': business,
            'checked_at_utc': datetime.now(timezone.utc).isoformat()}


def main() -> None:
    state = {'schema_version': 1, 'phase': 'distinct_seed_healthy_calibration',
             'seed': SEED, 'first_phase_attempts_frozen': 845,
             'first_phase_effective_frozen': 68, 'runs': {}, 'finished': False}
    if STATE.exists():
        state = json.loads(STATE.read_text())
        assert state['seed'] == SEED
        assert state['first_phase_attempts_frozen'] == 845
        assert state['first_phase_effective_frozen'] == 68
    for run_id in RUN_IDS:
        if run_id in state['runs']:
            continue
        out = RUN_ROOT / run_id
        assert not out.exists(), f'Unreceipted calibration raw exists: {out}'
        guard = resource_guard()
        manifest = run(run_id=run_id, seed=SEED)
        assert manifest['plan'] == [] and manifest['seed'] == SEED
        files = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
        state['runs'][run_id] = {'guard': guard, 'manifest': manifest,
                                 'raw_file_sha256': files}
        save(state)
        print(f'checkpoint {run_id}', flush=True)
    state['finished'] = True
    save(state)
    print('seed2 healthy calibration complete', flush=True)


if __name__ == '__main__':
    main()
