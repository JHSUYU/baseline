#!/usr/bin/env python3
"""Read-only recount of closed full-stage raw trials and their SHA receipts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from calibrate import HERE, FIRST, ROOT, sha, stamp
from fault_audit import check


def recount() -> dict:
    state_path = HERE / 'full-state.json'
    state = json.loads(state_path.read_text())
    old = json.loads((FIRST / 'campaign-state.json').read_text())
    healthy = json.loads((HERE / 'healthy-audit.json').read_text())
    pilot = json.loads((HERE / 'pilot-state.json').read_text())
    old_plans = set(old['known_plans'])
    pilot_plans = {'|||'.join(plan) for plan in pilot['plans']}
    assert state['first_phase_campaign_state_sha256'] == sha(FIRST / 'campaign-state.json')
    assert state['healthy_audit_sha256'] == sha(HERE / 'healthy-audit.json')
    assert state['pilot_audit_sha256'] == sha(HERE / 'pilot-audit.json')
    assert state['attempts'] == len(state['trials'])
    assert state['effective'] == sum(bool(row['effective']) for row in state['trials'])
    assert len(state['seen']) == len(set(state['seen']))
    assert not old_plans.intersection(state['seen'])
    assert pilot_plans.issubset(state['seen'])
    issues: list[str] = []
    cases = []
    raw_lines = []
    target_throws = 0
    for number, row in enumerate(state['trials'], 1):
        run_id = f'trial-{number:03d}'
        out = ROOT / run_id
        if row['run_id'] != run_id:
            issues.append(f'{run_id}: noncontiguous trial ID')
            continue
        manifest_path = out / 'run.json'
        if not manifest_path.is_file():
            issues.append(f'{run_id}: missing run.json')
            continue
        manifest = json.loads(manifest_path.read_text())
        try:
            assert sha(manifest_path) == row['run_json_sha256']
            assert manifest['run_id'] == run_id and manifest['plan'] == row['plan']
            assert manifest['original_junit'] is True
            assert manifest['original_junit_class_sha256'] == healthy['original_junit_class_sha256']
            assert manifest['classpath_has_graphchecker_runtime'] is False
            assert manifest['junit_exit'] == row['junit_exit']
            assert manifest['coverage']['available'] == row['coverage_available']
            console = (out / 'console.log').read_text(errors='replace')
            assert manifest['junit_summary_present'] == ('SOLR18_ORIGINAL_JUNIT ran=1 ignored=0 failures=0' in console)
            assert manifest['test_started_count'] == console.count('SOLR18_TEST_STARTED ')
            assert manifest['assumption_failure_count'] == console.count('SOLR18_ASSUMPTION_FAILURE ')
            for name, expected in manifest['raw_file_sha256'].items():
                assert sha(out / name) == expected, name
            audit = check(out / 'events.tsv', row['plan'])
            assert audit == manifest['fault_audit'] == row['fault_audit']
            effective = bool(audit['effective'] and manifest['test_started_count'] == 1
                             and manifest['assumption_failure_count'] == 0)
            assert effective == row['effective']
            assert manifest['junit_exit'] != 0 or manifest['junit_summary_present']
            assert row['new_production_methods_vs_healthy'] == manifest['coverage'].get('new_vs_healthy', {}).get('methods', [])
            assert row['new_production_lines_vs_healthy'] == manifest['coverage'].get('new_vs_healthy', {}).get('lines', [])
            target_throws += int(audit['target_outcome'] == 'TARGET_THROW')
            cases.append({'run_id': run_id, 'effective': effective,
                          'junit_exit': manifest['junit_exit'],
                          'target_outcome': audit['target_outcome'],
                          'fault_count': len(row['plan']),
                          'actor': audit['target_actor'],
                          'elapsed_seconds': manifest['elapsed_seconds'],
                          'events_sha256': manifest['raw_file_sha256']['events.tsv'],
                          'jacoco_sha256': manifest['raw_file_sha256']['jacoco.exec'],
                          'run_json_sha256': row['run_json_sha256']})
            for path in sorted(out.rglob('*')):
                if path.is_file():
                    raw_lines.append(f'{run_id}/{path.relative_to(out)}\t{sha(path)}\n')
        except (AssertionError, KeyError, ValueError) as error:
            issues.append(f'{run_id}: {error!r}')
    return {'case_id': 'SOLR-18', 'phase': 'alternate_original_junit_full',
            'audited_at_utc': stamp(), 'checkpoint_sha256': sha(state_path),
            'closed_attempts': state['attempts'], 'strict_effective': state['effective'],
            'inflight': state['inflight'] and state['inflight']['run_id'],
            'finished': state['finished'], 'stop_reason': state['stop_reason'],
            'target_throw_count': target_throws, 'fault_count_max': max((x['fault_count'] for x in cases), default=0),
            'feedback_policy_sha256': state.get('feedback_policy_sha256'),
            'promoted_observed_roots': state.get('promoted_observed_roots', []),
            'raw_file_count': len(raw_lines),
            'raw_sha256_manifest_sha256': hashlib.sha256(''.join(raw_lines).encode()).hexdigest(),
            'cases': cases, 'issues': issues}


if __name__ == '__main__':
    result = recount()
    print(json.dumps(result, sort_keys=True, indent=2))
    if result['issues']:
        raise SystemExit(1)
