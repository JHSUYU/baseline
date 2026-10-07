#!/usr/bin/env python3
"""Clean original-JUnit replay of one actor-exact selected throw; outside budget."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from campaign_v2 import audit_trial, strict, target_after
from calibrate_v2 import events
from run_v2 import run


HERE = Path(__file__).resolve().parent
STATE = HERE / 'campaign/state.json'
SOURCE_TRIAL = 4
OUTPUT = HERE / 'replay-trial-004'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    state = json.loads(STATE.read_text())
    if not state.get('stopped'):
        raise RuntimeError('clean replay waits for the main campaign to end')
    selected = state['trials'][SOURCE_TRIAL - 1]
    if (selected['number'] != SOURCE_TRIAL or not selected['effective'] or
            not selected['target_exception'] or len(selected['sequence']) != 3):
        raise RuntimeError('saved candidate is not the expected strict three-fault trial')
    if OUTPUT.exists():
        raise RuntimeError('replay output already exists; preserve it instead of overwriting')
    OUTPUT.mkdir()
    original_plan = HERE / 'campaign' / f'trial-{SOURCE_TRIAL:03d}/fault.properties'
    copied_plan = OUTPUT / 'fault.properties'
    shutil.copy2(original_plan, copied_plan)
    exit_code = run(OUTPUT, copied_plan)
    rows = events(OUTPUT / 'events.jsonl')
    applied = [row for row in rows if row['event'] == 'IO_APPLIED']
    exact = strict(rows, selected['sequence'])
    after, thrown = target_after(rows, applied) if exact else (False, False)
    actor = audit_trial(rows)
    log = (OUTPUT / 'junit.log').read_text(errors='replace')
    result = {
        'case_id': 'SOLR-01', 'identity_version': 'actor-v2',
        'non_budget_replay': True, 'original_trial': SOURCE_TRIAL,
        'plan_sha256': digest(copied_plan),
        'same_plan_as_original': digest(copied_plan) == digest(original_plan),
        'strict': exact, 'applied_faults': len(applied), 'target_after_fault': after,
        'selected_throw': thrown, 'junit_exit': exit_code,
        'junit_selected_exception':
            'SOLR01_JUNIT_FAILURE testAliasHandling' in log and
            'Tried fetching aliases using all the node names we knew of' in log,
        'actor_audit': actor,
        'elapsed_seconds': json.loads((OUTPUT / 'run.json').read_text())['elapsed_seconds'],
        'raw_sha256': {name: digest(OUTPUT / name) for name in
                       ('events.jsonl', 'jacoco.exec', 'junit.log',
                        'run.json', 'fault.properties')},
    }
    path = OUTPUT / 'replay-summary.json'
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: result[key] for key in
                      ('strict', 'applied_faults', 'target_after_fault',
                       'selected_throw', 'junit_exit', 'junit_selected_exception',
                       'elapsed_seconds')}, sort_keys=True))
    if not (result['same_plan_as_original'] and exact and after and thrown and
            exit_code == 1 and result['junit_selected_exception']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
