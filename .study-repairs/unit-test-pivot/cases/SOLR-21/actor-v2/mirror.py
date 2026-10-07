#!/usr/bin/env python3
"""Mirror the actor-V2 checkpoint into the 102-case result without old trials."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
RESULT = HERE.parent / 'result.json'
REMOTE = ('/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/'
          'SOLR-21/actor-v2/campaign/progress.json')
SSH = ['ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'ZhenyuLi@node2']


def atomic(path: Path, value: object) -> None:
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def fetch() -> dict:
    output = subprocess.run(SSH + ['cat', REMOTE], capture_output=True,
                            text=True, check=True).stdout
    return json.loads(output)


def publish(progress: dict) -> dict:
    result = json.loads(RESULT.read_text())
    healthy = json.loads((HERE / 'calibration-receipt.json').read_text())
    legacy = result.setdefault('legacy_coarse_actor', {})
    if 'source_review' not in legacy and 'source_review' in result:
        legacy['source_review'] = result['source_review']
    stage = progress['status']
    if stage == 'running':
        status = ('actor_v2_pilot_running' if progress['budget']['max_effective'] <= 10
                  else 'actor_v2_fuzz_running')
    elif stage == 'budget_complete' and progress['budget']['max_effective'] <= 10:
        status = 'actor_v2_pilot_complete_pending_review'
    elif stage == 'candidate_target_exception':
        status = 'target_exception_candidate_source_review'
    else:
        status = 'actor_v2_source_audit_pending'
    healthy_seconds = sum(run['elapsed_seconds'] for run in healthy['healthy_runs'])
    result.update({
        'status': status,
        'methodology': 'actor_aware_coverage_io_original_cluster_junit_v2',
        'fault_trials': progress['selected_plans'],
        'strict_injections': progress['strict_injections'],
        'post_fault_target_reach_trials': progress['post_fault_target_reach_trials'],
        'target_after_fault': progress['post_fault_target_reach_trials'],
        'target_exception_after_fault_trials': progress['target_exception_after_fault_trials'],
        'coverage_gain': progress['production_probe_gain'],
        'io_family_gain': progress['io_family_gain'],
        'elapsed_seconds': round(healthy_seconds + progress['elapsed_seconds'], 3),
        'quality_complete': False,
        'bug_mark': 'none',
        'reason': ('Two new actor-bound healthy JUnit seeds pass; independent V2 '
                   'fault campaign and source review are pending.'),
        'actor_v2_healthy_elapsed_seconds': round(healthy_seconds, 3),
        'actor_v2_fault_elapsed_seconds': progress['elapsed_seconds'],
        'actor_v2_calibration': {
            'agent_sha256': healthy['agent_sha256'],
            'stable_bound_selectors': healthy['stable_bound_selectors'],
            'stable_file_selectors': healthy['stable_file_selectors'],
            'healthy_trace_sha256': [run['trace_sha256'] for run in healthy['healthy_runs']],
            'healthy_target': [run['target'] for run in healthy['healthy_runs']],
        },
        'actor_v2_progress': progress,
        'evidence': str(HERE.relative_to(BASE) / 'calibration-receipt.json'),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    })
    result['source_review'] = {
        'source': 'CoreContainer.reload(String, UUID) at CoreContainer.java:1765',
        'code_condition': 'docCollection.getReplica(coreNodeName) must be nonnull',
        'decision': 'Actor-bound V2 fault campaign is running; no source conclusion yet.',
        'original_junit': 'CollectionReloadTest#testReloadedLeaderStateAfterZkSessionLoss',
        'sequence_limit': 'The original test reloads before explicitly expiring its ZooKeeper session.',
    }
    atomic(HERE / 'progress-mirror.json', progress)
    atomic(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    arguments = parser.parse_args()
    while True:
        try:
            progress = fetch()
            result = publish(progress)
            print(json.dumps({'status': result['status'],
                              'selected': result['fault_trials'],
                              'effective': result['post_fault_target_reach_trials']},
                             sort_keys=True), flush=True)
            if arguments.once or progress['status'] != 'running':
                return
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            if arguments.once:
                raise
            print(f'mirror retry: {error}', flush=True)
        time.sleep(10)


if __name__ == '__main__':
    main()
