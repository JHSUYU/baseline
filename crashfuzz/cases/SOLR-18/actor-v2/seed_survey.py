#!/usr/bin/env python3
"""Bounded healthy original-JUnit survey for the frozen selected phase."""
from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone

from actor_audit import audit
from run_native import RUN_ROOT, run
from seed2_calibrate import resource_guard, sha


HERE = Path(__file__).resolve().parent
STATE = HERE / 'seed-survey-state.json'
SEEDS = (
    ('seed3', '61BC42E0D9357A8F'),
    ('seed4', '0F1E2D3C4B5A6978'),
    ('seed5', 'C4E51A6B29D7038F'),
    ('seed6', '7A63D20F4B91E5C8'),
)


def save(state: dict) -> None:
    temp = STATE.with_suffix('.json.tmp')
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    os.replace(temp, STATE)


def run_one(run_id: str, seed: str, old_roots: set[str]) -> dict:
    out = RUN_ROOT / run_id
    assert not out.exists(), f'Unreceipted raw exists: {out}'
    guard = resource_guard()
    manifest = run(run_id=run_id, seed=seed)
    checked = audit(out / 'events.tsv', [])
    roots = set(checked.get('relevant_same_client_io_selectors', []))
    files = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    return {'guard': guard, 'manifest': manifest, 'actor_audit': checked,
            'root_count': len(roots), 'new_roots': sorted(roots - old_roots),
            'raw_file_sha256': files}


def main() -> None:
    frontier = json.loads((HERE / 'frontier-inventory-701plus.json').read_text())
    old_roots = {row['selector'] for row in frontier['roots']}
    state = {'schema_version': 1, 'phase': 'distinct_seed_target_phase_survey',
             'first_phase_attempts_frozen': 845,
             'first_phase_effective_frozen': 68,
             'first_phase_known_roots_sha256': sha(HERE / 'frontier-inventory-701plus.json'),
             'seeds': {}, 'finished': False}
    if STATE.exists():
        state = json.loads(STATE.read_text())
        assert state['first_phase_attempts_frozen'] == 845
        assert state['first_phase_effective_frozen'] == 68
        assert state['first_phase_known_roots_sha256'] == sha(HERE / 'frontier-inventory-701plus.json')
    for label, seed in SEEDS:
        item = state['seeds'].setdefault(label, {'seed': seed, 'runs': {}})
        assert item['seed'] == seed
        first = f'healthy-v3-{label}-a'
        if first not in item['runs']:
            item['runs'][first] = run_one(first, seed, old_roots)
            save(state)
            print('checkpoint', first, flush=True)
        first_result = item['runs'][first]
        if first_result['actor_audit']['selected_target'] and first_result['new_roots']:
            second = f'healthy-v3-{label}-b'
            if second not in item['runs']:
                item['runs'][second] = run_one(second, seed, old_roots)
                save(state)
                print('checkpoint', second, flush=True)
        item['stable_new_roots'] = sorted(set.intersection(*(
            set(row['new_roots']) for row in item['runs'].values())))
        item['qualifies_new_phase'] = bool(
            len(item['runs']) == 2
            and all(row['actor_audit']['selected_target']
                    and row['manifest']['junit_exit'] == 0
                    and row['manifest']['junit_summary_present']
                    and row['manifest']['test_started_count'] == 1
                    and row['manifest']['assumption_failure_count'] == 0
                    for row in item['runs'].values())
            and item['stable_new_roots'])
        save(state)
    state['finished'] = True
    state['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    save(state)
    print('bounded seed survey complete', flush=True)


if __name__ == '__main__':
    main()
