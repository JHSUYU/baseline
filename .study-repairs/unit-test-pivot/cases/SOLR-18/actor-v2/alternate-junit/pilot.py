#!/usr/bin/env python3
"""At most five unique singleton trials, one atomic checkpoint per run."""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path

from calibrate import HERE, FIRST, ROOT, atomic_json, sha, stamp
from fault_run import run

STATE = HERE / 'pilot-state.json'
CONTROLLER_LOCK = HERE / 'pilot-controller.lock'


def initial() -> dict:
    healthy = json.loads((HERE / 'healthy-audit.json').read_text())
    assert healthy['stable_novel_root_count'] == 183
    plans = healthy['pilot_singleton_plans']
    assert len(plans) == 5 and all(len(plan) == 1 for plan in plans)
    assert len({tuple(plan) for plan in plans}) == 5
    old = json.loads((FIRST / 'campaign-state.json').read_text())
    assert old['attempts'] == 845 and old['effective'] == 68
    assert not any(plan[0] in old['known_plans'] for plan in plans)
    return {'schema_version': 1, 'phase': 'alternate_junit_singleton_pilot',
            'first_phase_attempts_frozen': 845, 'first_phase_effective_frozen': 68,
            'first_phase_campaign_state_sha256': sha(FIRST / 'campaign-state.json'),
            'healthy_audit_sha256': sha(HERE / 'healthy-audit.json'),
            'plans': plans, 'trials': [], 'inflight': None, 'finished': False,
            'effective': 0, 'attempts': 0, 'started_at_utc': stamp()}


def save(state: dict) -> None:
    atomic_json(STATE, state)


def finish_trial(state: dict, manifest: dict) -> None:
    job = state['inflight']
    assert manifest['run_id'] == job['run_id'] and manifest['plan'] == job['plan']
    audit = manifest['fault_audit'] or {}
    effective = bool(audit.get('effective') and manifest['test_started_count'] == 1
                     and manifest['assumption_failure_count'] == 0)
    coverage = manifest['coverage']
    gain = coverage.get('new_vs_healthy', {})
    row = {'run_id': job['run_id'], 'plan': job['plan'],
           'junit_exit': manifest['junit_exit'],
           'junit_summary_present': manifest['junit_summary_present'],
           'elapsed_seconds': manifest['elapsed_seconds'],
           'fault_audit': audit, 'effective': effective,
           'new_production_methods_vs_healthy': gain.get('methods', []),
           'new_production_lines_vs_healthy': gain.get('lines', []),
           'coverage_available': coverage['available'],
           'run_json_sha256': sha(ROOT / job['run_id'] / 'run.json'),
           'finished_at_utc': stamp()}
    state['trials'].append(row)
    state['attempts'] = len(state['trials'])
    state['effective'] = sum(item['effective'] for item in state['trials'])
    state['inflight'] = None
    if state['attempts'] == len(state['plans']):
        state['finished'] = True
        state['finished_at_utc'] = stamp()
    save(state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--one', action='store_true', required=True)
    parser.parse_args()
    with CONTROLLER_LOCK.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.exists() else initial()
        assert state['healthy_audit_sha256'] == sha(HERE / 'healthy-audit.json')
        assert state['first_phase_campaign_state_sha256'] == sha(FIRST / 'campaign-state.json')
        assert state['attempts'] == len(state['trials']) <= 5
        assert not state['finished'] or state['attempts'] == 5
        if state['finished']:
            print(json.dumps({'status': 'pilot_complete', 'attempts': 5,
                              'effective': state['effective']}))
            return
        if state['inflight'] is None:
            index = state['attempts']
            state['inflight'] = {'run_id': f'pilot-{index + 1:03d}',
                                 'plan': state['plans'][index],
                                 'selected_at_utc': stamp()}
            save(state)
        job = state['inflight']
        out = ROOT / job['run_id']
        if (out / 'run.json').exists():
            manifest = json.loads((out / 'run.json').read_text())
        else:
            assert not out.exists(), f'partial raw needs manual reconciliation: {out}'
            manifest = run(job['run_id'], job['plan'], 'alternate_junit_singleton_pilot')
        finish_trial(state, manifest)
        last = state['trials'][-1]
        print(json.dumps({'run_id': last['run_id'], 'junit_exit': last['junit_exit'],
                          'effective': last['effective'],
                          'target_outcome': last['fault_audit'].get('target_outcome'),
                          'new_methods': len(last['new_production_methods_vs_healthy']),
                          'attempts': state['attempts'], 'effective_total': state['effective']},
                         sort_keys=True))


if __name__ == '__main__':
    main()
