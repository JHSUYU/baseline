#!/usr/bin/env python3
"""Audit the frozen 10-run checkpoint before rotating in core-file I/O."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE / 'campaign'
BACKUP = CAMPAIGN / 'migrations/0001-file-family'
OLD_STATE_SHA = 'bace774587e63abe36c4c37af6dca1f4886d1131dd7d3fe66f5dd26cdb07a0d0'
OLD_FUZZER_SHA = 'd6b7d9f39d0b512234e3521d6d7f03b184d6f8d0fc4cd51e4fea2043c276e263'
FUZZER_KEY = 'actor-v2/fuzz_v2.py'


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stable_digest(value: object) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def frozen(raw: bytes) -> dict:
    if digest(raw) != OLD_STATE_SHA:
        raise RuntimeError('live pilot state differs from frozen ten-run checkpoint')
    state = json.loads(raw)
    if (state['status'] != 'budget_complete' or len(state['completed']) != 10
            or state['active'] is not None or state['budget'] != {
                'max_effective': 10, 'max_faults': 8, 'max_selected_plans': 64}):
        raise RuntimeError('checkpoint is not the reviewed pilot boundary')
    if state['runner_sha256'][FUZZER_KEY] != OLD_FUZZER_SHA:
        raise RuntimeError('checkpoint references an unexpected old scheduler')
    if any(row['trial_number'] != number or not row['strict_injection']
           or not row['target_preserved'] or row['exact_target_throw_after_last_fault']
           for number, row in enumerate(state['completed'], 1)):
        raise RuntimeError('frozen pilot audit no longer matches ten valid runs')
    return state


def preserve(name: str, raw: bytes) -> None:
    path = BACKUP / name
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError(f'backup changed: {path}')
    else:
        path.write_bytes(raw)


def prepare() -> None:
    state_raw = (CAMPAIGN / 'state.json').read_bytes()
    frozen(state_raw)
    fuzzer_raw = (HERE / 'fuzz_v2.py').read_bytes()
    if digest(fuzzer_raw) != OLD_FUZZER_SHA:
        raise RuntimeError('prepare must run before installing the new scheduler')
    BACKUP.mkdir(parents=True, exist_ok=True)
    preserve('state-before.json', state_raw)
    preserve('progress-before.json', (CAMPAIGN / 'progress.json').read_bytes())
    preserve('fuzz-before.py', fuzzer_raw)
    print(json.dumps({'phase': 'prepare', 'old_state_sha256': digest(state_raw),
                      'old_fuzzer_sha256': digest(fuzzer_raw)}, sort_keys=True))


def apply() -> None:
    state_raw = (BACKUP / 'state-before.json').read_bytes()
    state = frozen(state_raw)
    if digest((BACKUP / 'fuzz-before.py').read_bytes()) != OLD_FUZZER_SHA:
        raise RuntimeError('old scheduler backup is invalid')
    import fuzz_v2  # Imported only after the new scheduler has been staged.

    actual_hashes = fuzz_v2.runner_hashes()
    new_fuzzer_sha = actual_hashes[FUZZER_KEY]
    if new_fuzzer_sha == OLD_FUZZER_SHA:
        raise RuntimeError('new scheduler was not staged')
    old_hashes = state['runner_sha256']
    if {k: v for k, v in actual_hashes.items() if k != FUZZER_KEY} != {
            k: v for k, v in old_hashes.items() if k != FUZZER_KEY}:
        raise RuntimeError('an agent, JUnit, or other runner dependency changed')
    trial_numbers = [row['trial_number'] for row in state['completed']]
    queue_count = len(state['queue'])
    probe_count = len(state['covered_probes'])
    choice = fuzz_v2.select(copy.deepcopy(state))
    selected = choice['sequence'][-1]
    if (selected['marker'] != 'FAULT:FILE:core.properties:read'
            or selected['actorKey'] != 'JETTY/node1'):
        raise RuntimeError('new round 11 does not select the bound core-file read')
    new_state = copy.deepcopy(state)
    new_state['runner_sha256'][FUZZER_KEY] = new_fuzzer_sha
    new_state['scheduler_migration_id'] = '0001-file-family-after-reviewed-pilot10'
    if ([row['trial_number'] for row in new_state['completed']] != trial_numbers
            or len(new_state['queue']) != queue_count
            or len(new_state['covered_probes']) != probe_count):
        raise RuntimeError('migration altered completed trials, queue, or coverage')
    new_raw = (json.dumps(new_state, indent=2, sort_keys=True) + '\n').encode()
    report = {
        'migration_id': new_state['scheduler_migration_id'],
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'old_state_sha256': digest(state_raw),
        'new_state_sha256': digest(new_raw),
        'old_fuzzer_sha256': OLD_FUZZER_SHA,
        'new_fuzzer_sha256': new_fuzzer_sha,
        'completed_trials': trial_numbers,
        'completed_digest_sha256': stable_digest(state['completed']),
        'queue_count': queue_count,
        'queue_digest_sha256': stable_digest(state['queue']),
        'covered_probe_count': probe_count,
        'next_selected_plan_id': choice['id'],
        'next_selected_fault': selected,
        'changed_fields': ['runner_sha256.' + FUZZER_KEY,
                           'scheduler_migration_id'],
    }
    report_path = BACKUP / 'migration.json'
    if report_path.exists():
        prior = json.loads(report_path.read_text())
        for key in ('old_state_sha256', 'new_state_sha256',
                    'new_fuzzer_sha256', 'completed_digest_sha256',
                    'queue_digest_sha256', 'next_selected_plan_id'):
            if prior[key] != report[key]:
                raise RuntimeError('existing migration receipt contradicts checkpoint')
    else:
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    live = CAMPAIGN / 'state.json'
    live_hash = digest(live.read_bytes())
    if live_hash == digest(new_raw):
        pass
    elif live_hash == OLD_STATE_SHA:
        temporary = CAMPAIGN / '.state.json.migration.tmp'
        temporary.write_bytes(new_raw)
        temporary.replace(live)
    else:
        raise RuntimeError('live checkpoint changed during migration')
    print(json.dumps({'phase': 'apply', 'old_state_sha256': OLD_STATE_SHA,
                      'new_state_sha256': digest(new_raw),
                      'next_selected_plan_id': choice['id']}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'apply'))
    phase = parser.parse_args().phase
    prepare() if phase == 'prepare' else apply()
