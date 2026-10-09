#!/usr/bin/env python3
"""Recount the bounded distinct-seed healthy survey from raw traces."""
from __future__ import annotations

import json
from pathlib import Path

from actor_audit import actor, audit, events
from run_native import RUN_ROOT
from seed2_calibrate import sha


HERE = Path(__file__).resolve().parent
ORIGINAL_JUNIT_SHA = '7674e0e501483b11108f72129a2a68ff54ae5c6d35c4862d6546a132f439f402'


def selected_phase(rows: list) -> dict:
    apply = [row for row in rows if row[1] == 'APPLY_MODIFICATION'
             and len(row[3]) >= 3 and row[3][1] == 'TEST_BODY' and actor(row[3])]
    assert len(apply) >= 2
    first, second = apply[:2]
    guard = next((row for row in rows if row[1] == 'TARGET_GUARD'
                  and row[0] > first[0] and len(row[3]) >= 7
                  and row[3][0] == first[3][0]
                  and row[3][3:6] == ['1', '1', '0']
                  and actor(row[3]) == actor(first[3])), None)
    return {'first_apply_seq': first[0], 'next_apply_seq': second[0],
            'first_version1_guard_seq': guard[0] if guard else None,
            'version1_guard_in_original_phase': bool(guard and guard[0] < second[0])}


def main() -> None:
    terminal = json.loads((HERE / 'terminal-receipt.json').read_text())
    for name in ('campaign-state.json', 'trial-ledger.jsonl',
                 'frontier-inventory-701plus.json'):
        assert sha(HERE / name) == terminal['evidence_sha256'][name], name
    # Node0 and node2 independently wrote terminal audits. The local audit
    # filename differs by host; both exact digests are frozen in the receipt.
    assert sha(HERE / 'final-audit.json') in {
        terminal['evidence_sha256']['final-audit.json'],
        terminal['evidence_sha256']['node2-checkpoint-audit.json']}
    frontier = json.loads((HERE / 'frontier-inventory-701plus.json').read_text())
    old = {row['selector'] for row in frontier['roots']}
    assert len(old) == 21
    seed2 = json.loads((HERE / 'seed2-calibration-state.json').read_text())
    survey = json.loads((HERE / 'seed-survey-state.json').read_text())
    assert seed2['finished'] and survey['finished']
    assert seed2['first_phase_attempts_frozen'] == survey['first_phase_attempts_frozen'] == 845
    assert seed2['first_phase_effective_frozen'] == survey['first_phase_effective_frozen'] == 68
    all_runs = dict(seed2['runs'])
    for item in survey['seeds'].values():
        all_runs.update(item['runs'])
    assert len(all_runs) == 6
    results = {}
    for rid, recorded in sorted(all_runs.items()):
        out = RUN_ROOT / rid
        for name, digest in recorded['raw_file_sha256'].items():
            assert sha(out / name) == digest, (rid, name)
        manifest = json.loads((out / 'run.json').read_text())
        assert manifest == recorded['manifest'], rid
        assert manifest['junit_exit'] == 0 and manifest['junit_summary_present']
        assert manifest['test_started_count'] == 1
        assert manifest['assumption_failure_count'] == 0
        assert manifest['original_junit'] and manifest['plan'] == []
        assert manifest['junit_class_sha256'] == ORIGINAL_JUNIT_SHA
        checked = audit(out / 'events.tsv', [])
        rows = events(out / 'events.tsv')
        phase = selected_phase(rows)
        assert checked['selected_target'] == phase['version1_guard_in_original_phase']
        roots = set(checked.get('relevant_same_client_io_selectors', []))
        # The two phase-missed runs are also checked against the later
        # version-1 guard, only to inventory roots, never to count a target.
        if not checked['selected_target']:
            guard_seq = phase['first_version1_guard_seq']
            assert guard_seq is not None
            guard = next(row for row in rows if row[0] == guard_seq)
            roots = {row[3][0] + '@@' + row[3][1] for row in rows
                     if row[1] == 'IO' and len(row[3]) >= 3
                     and actor(row[3]) == actor(guard[3]) and row[0] < guard_seq}
        new = sorted(roots - old)
        assert not new, (rid, new)
        results[rid] = {
            'seed': manifest['seed'], 'original_junit_elapsed_seconds': manifest['elapsed_seconds'],
            'original_junit_passed': True, 'selected_target': checked['selected_target'],
            'selected_target_json_equal': checked.get('target_json_equal'),
            'selected_target_actor': checked.get('target_actor'),
            'phase': phase, 'same_client_pretarget_root_count': len(roots),
            'new_roots_against_first_phase_21': new,
            'events_sha256': sha(out / 'events.tsv'),
            'jacoco_sha256': sha(out / 'jacoco.exec'),
            'run_sha256': sha(out / 'run.json'),
        }
    assert {row['seed'] for row in results.values()} == {
        seed2['seed'], *(v['seed'] for v in survey['seeds'].values())}
    result = {
        'schema_version': 1, 'case_id': 'SOLR-18',
        'first_phase_terminal_receipt_sha256': sha(HERE / 'terminal-receipt.json'),
        'first_phase_attempts': 845, 'first_phase_effective': 68,
        'first_phase_campaign_state_sha256': sha(HERE / 'campaign-state.json'),
        'first_phase_trial_ledger_sha256': sha(HERE / 'trial-ledger.jsonl'),
        'first_phase_known_same_client_roots': len(old),
        'seed2_calibration_state_sha256': sha(HERE / 'seed2-calibration-state.json'),
        'seed_survey_state_sha256': sha(HERE / 'seed-survey-state.json'),
        'raw_runs_verified': len(results), 'distinct_new_seeds': 5,
        'new_same_client_pretarget_roots': 0,
        'qualifying_supplemental_phase_seeds': [],
        'runs': results,
        'conclusion': 'No new stable root eligible for a separate supplemental phase; first phase remains plan-exhausted/inconclusive.',
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
