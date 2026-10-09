#!/usr/bin/env python3
"""Recount the alternate campaign from TSV events without importing its oracle."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path('/users/ZhenyuLi/solr18-alternate-junit-runs')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_events(path: Path) -> list[list[str]]:
    rows = [line.split('\t') for line in path.read_text().splitlines()]
    assert all(len(row) >= 3 for row in rows)
    assert all(int(a[0]) < int(b[0]) for a, b in zip(rows, rows[1:]))
    return rows


def actor(row: list[str]) -> str | None:
    identities = [part[6:] for part in row[3:] if part.startswith('actor=')]
    return identities[0] if len(identities) == 1 and identities[0].startswith('ZKCLIENT@') else None


def selected_guard(rows: list[list[str]]) -> tuple[list[str] | None, list[str] | None, str | None]:
    starts = [row for row in rows if row[1] == 'TEST_STARTED']
    finishes = [row for row in rows if row[1] == 'TEST_FINISHED']
    if len(starts) != 1 or len(finishes) != 1 or int(starts[0][0]) >= int(finishes[0][0]):
        return None, None, None
    start, finish = int(starts[0][0]), int(finishes[0][0])
    mutations = [row for row in rows if row[1] == 'APPLY_MODIFICATION'
                 and start < int(row[0]) < finish and len(row) >= 6
                 and row[4] == 'CREATE_ALIAS_CMD' and actor(row)]
    if not mutations:
        return None, None, None
    first = mutations[0]
    manager, chosen_actor = first[3], actor(first)
    next_mutation = next((int(row[0]) for row in rows
                          if row[1] == 'APPLY_MODIFICATION' and int(row[0]) > int(first[0])
                          and len(row) > 3 and row[3] == manager), finish)
    limit = min(next_mutation, finish)
    guard = next((row for row in rows if row[1] == 'TARGET_GUARD'
                  and int(first[0]) < int(row[0]) < limit and len(row) >= 10
                  and row[3] == manager and row[6:9] == ['1', '1', '0']
                  and actor(row) == chosen_actor), None)
    if guard is None:
        return None, None, chosen_actor
    outcome = next((row for row in rows if row[1] in ('TARGET_EQUAL_CHECK', 'TARGET_THROW')
                    and int(row[0]) > int(guard[0]) and row[3:9] == guard[3:9]
                    and actor(row) == chosen_actor), None)
    return guard, outcome, chosen_actor


def trial(row: dict) -> dict:
    run_id = row['run_id']
    out = ROOT / run_id
    manifest_path = out / 'run.json'
    assert sha(manifest_path) == row['run_json_sha256']
    manifest = json.loads(manifest_path.read_text())
    assert manifest['run_id'] == run_id and manifest['plan'] == row['plan']
    assert sha(out / 'events.tsv') == manifest['raw_file_sha256']['events.tsv']
    rows = read_events(out / 'events.tsv')
    matched = [event for event in rows if event[1] == 'FAULT_MATCHED']
    applied = [event for event in rows if event[1] == 'FAULT_APPLIED']
    plan = row['plan']
    strict = (len(matched) == len(applied) == len(plan)
              and [event[3] + '@@' + event[4] for event in matched] == plan
              and [event[3] + '@@' + event[4] for event in applied] == plan
              and all(int(m[0]) + 1 == int(a[0]) and m[5] == a[5] == str(index)
                      for index, (m, a) in enumerate(zip(matched, applied))))
    guard, outcome, chosen_actor = selected_guard(rows)
    all_bound = bool(strict and guard is not None
                     and all(actor(event) == chosen_actor for event in applied))
    postfinal = bool(guard is not None and applied
                     and int(guard[0]) > int(applied[-1][0]))
    outcome_name = outcome[1] if outcome is not None else None
    effective = bool(strict and all_bound and postfinal
                     and outcome_name in ('TARGET_EQUAL_CHECK', 'TARGET_THROW')
                     and manifest['test_started_count'] == 1
                     and manifest['assumption_failure_count'] == 0)
    equal = outcome[9] == 'true' if outcome_name == 'TARGET_EQUAL_CHECK' else None
    assert effective == row['effective']
    assert strict == row['fault_audit']['strict_ordered_faults']
    assert (guard is not None) == row['fault_audit']['selected_target']
    assert chosen_actor == row['fault_audit'].get('target_actor') or guard is None
    assert all_bound == row['fault_audit']['all_faults_on_target_client']
    assert postfinal == row['fault_audit']['target_after_final_fault']
    assert outcome_name == row['fault_audit']['target_outcome']
    assert equal == row['fault_audit']['target_json_equal']
    return {'run_id': run_id, 'fault_count': len(plan), 'strict_ordered_faults': strict,
            'selected_guard': guard is not None, 'same_live_client': all_bound,
            'postfinal_guard': postfinal, 'effective': effective,
            'target_outcome': outcome_name, 'target_json_equal': equal,
            'junit_exit': manifest['junit_exit'], 'events_sha256': sha(out / 'events.tsv')}


def recount() -> dict:
    state_path = HERE / 'full-state.json'
    state = json.loads(state_path.read_text())
    assert state['finished'] and state['inflight'] is None
    assert [r['run_id'] for r in state['trials']] == [f'trial-{n:03d}' for n in range(1, state['attempts'] + 1)]
    cases = [trial(row) for row in state['trials']]
    assert sum(item['effective'] for item in cases) == state['effective']
    assert all(item['junit_exit'] == 0 for item in cases if item['effective'])
    return {'case_id': 'SOLR-18', 'phase': 'alternate_original_junit_full',
            'audited_at_utc': datetime.now(timezone.utc).isoformat(),
            'implementation': 'independent TSV parser; no import of audit.py, fault_audit.py, or full_campaign.py',
            'full_checkpoint_sha256': sha(state_path), 'attempts': len(cases),
            'strict_effective': sum(item['effective'] for item in cases),
            'strict_ordered_injection_trials': sum(item['strict_ordered_faults'] for item in cases),
            'selected_guard_trials': sum(item['selected_guard'] for item in cases),
            'selected_target_equal_true_trials': sum(item['target_json_equal'] is True for item in cases),
            'selected_target_throw_trials': sum(item['target_outcome'] == 'TARGET_THROW' for item in cases),
            'effective_original_junit_passes': sum(item['effective'] and item['junit_exit'] == 0 for item in cases),
            'cases': cases, 'issues': []}


if __name__ == '__main__':
    print(json.dumps(recount(), indent=2, sort_keys=True))
