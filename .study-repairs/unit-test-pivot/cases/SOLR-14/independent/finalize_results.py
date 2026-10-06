#!/usr/bin/env python3
"""Finalize three checklist rows from completed independent Solr campaigns."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from build import HERE
from mirror import CASES, PIVOT


def atomic(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + f'.tmp.{os.getpid()}')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def main() -> None:
    main = json.loads((HERE / 'campaign/live-progress.json').read_text())
    native = json.loads((HERE / 'native/campaign/live-progress.json').read_text())
    assert main['status'] == 'budget_complete' and main['fault_trials'] == 80
    assert native['status'] in ('budget_complete', 'queue_exhausted')
    assert native['fault_trials'] == 80
    core = json.loads((HERE / 'native/campaign/production-coverage-audit.json').read_text())
    chaos = json.loads((HERE / 'supplemental/shardsplit/native-chaos-coverage-audit.json').read_text())
    review = json.loads((HERE / 'supplemental/shardsplit/solr15-native-candidate-source-review.json').read_text())
    assert review['classification'] == 'expected_protective_abort_not_new_bug'
    assert len(review['reproductions']) == 2
    native_extra_names = ('native-chaos-01', 'native-chaos-02', 'native-chaos-03',
                          'native-chaos-fault-01', 'native-chaos-fault-02',
                          'native-chaos-replay-01')
    native_extra = {name: json.loads((HERE / 'supplemental/shardsplit' / name / 'run.json').read_text())
                    for name in native_extra_names}
    for number in (14, 15, 16):
        case = f'SOLR-{number:02d}'
        path = CASES / case / 'result.json'
        row = json.loads(path.read_text())
        old_healthy = row['supplemental_original_chaos_healthy']
        old_faults = row['supplemental_original_chaos_fault_trials']
        supplemental_seconds = (
            row['supplemental_original_multinode_healthy']['elapsed_seconds']
            + sum(item['elapsed_seconds'] for item in old_healthy['repeat_runs'])
            + old_faults['elapsed_seconds']
            + sum(item['elapsed_seconds'] for item in native_extra.values()))
        post = (main['post_fault_target_reach_trials'][case]
                + (1 if number == 14 else 0)
                + native['post_fault_target_reach_trials'][case]
                + (1 if number == 15 else 0))
        exceptions = 1 if number == 15 else 0
        row.update({
            'shared_campaign_id': 'SOLR-14-15-16-original-split-tests',
            'trial_accounting': 'The same SplitShardTest and ShardSplitTest trials test all three checks; counts and elapsed time are shared across these rows.',
            'status': ('first_guard_reached_fatal_null_branch_not_observed' if number == 14 else
                       'quality_complete' if number == 15 else
                       'final_changed_owner_guard_not_observed'),
            'quality_complete': number == 15,
            'case_outcome': (review['classification'] if number == 15 else
                             'target_branch_not_observed'),
            'bug_mark': 'none',
            'target_reached': number != 16,
            'target_after_fault': post,
            'target_exception_after_fault_trials': exceptions,
            'coverage_gain': core['combined_gain_over_healthy']['new_production_branch_outcomes'],
            'coverage_gain_scope': 'original-release production branch outcomes, v1+native core campaigns; multi-node chaos separately audited',
            'production_coverage_core': core,
            'production_coverage_multinode_chaos': chaos,
            'supplemental_original_multinode_healthy': row['supplemental_original_multinode_healthy'],
            'supplemental_native_chaos_healthy': {
                'original_test': 'org.apache.solr.cloud.api.collections.ShardSplitTest#testSplitWithChaosMonkey',
                'passed': ['native-chaos-02', 'native-chaos-03'],
                'failed_no_fault_calibration': ['native-chaos-01'],
                'pass_seconds': [native_extra[name]['elapsed_seconds']
                                 for name in ('native-chaos-02', 'native-chaos-03')],
                'failed_calibration_seconds': native_extra['native-chaos-01']['elapsed_seconds'],
                'stable_selector': 'SOLR-14/independent/supplemental/shardsplit/native-chaos-plan-01-selection.json',
            },
            'supplemental_native_chaos_fault_trials': {
                'distinct_fault_trials': 2, 'strict_injections': 2,
                'replay_attempts': 1,
                'elapsed_fault_seconds': (native_extra['native-chaos-fault-01']['elapsed_seconds']
                                          + native_extra['native-chaos-fault-02']['elapsed_seconds']),
                'elapsed_replay_seconds': native_extra['native-chaos-replay-01']['elapsed_seconds'],
                'post_fault_target_check': 1 if number == 15 else 0,
                'post_fault_exact_throw': exceptions,
                'classification': review['classification'] if number == 15 else 'no_selected_throw',
                'evidence': 'SOLR-14/independent/supplemental/shardsplit/solr15-native-candidate-source-review.json',
            },
            'supplemental_elapsed_seconds': round(supplemental_seconds, 3),
            'total_measured_execution_seconds': round(row['elapsed_seconds'] + supplemental_seconds, 3),
            'supplemental_fault_trials': old_faults['fault_trials'] + 2,
            'total_distinct_fault_trials_all_workloads': row['fault_trials'] + old_faults['fault_trials'] + 2,
            'total_strict_fault_trials_all_workloads': row['strict_injections']
                                                    + old_faults['strict_injections'] + 2,
            'target_exception_source_review': (
                {'classification': review['classification'],
                 'reproductions': len(review['reproductions']),
                 'evidence': 'SOLR-14/independent/supplemental/shardsplit/solr15-native-candidate-source-review.json'}
                if number == 15 else None),
            'reason': (
                'The first live-node guard was reached in original embedded-cluster JUnit runs, '
                'but no strict post-fault run made its null branch true.' if number == 14 else
                'Two ordered native ZK faults reproducibly reached the exact throw, but original '
                'source and the unchanged chaos JUnit classify it as a deliberate abort after '
                'the test stops the parent leader; child shards entered RECOVERY_FAILED and '
                'document consistency assertions passed.' if number == 15 else
                'The original JUnit workloads and fault runs never reached the final '
                'ephemeral-owner-change guard. This branch remains untested.'),
            'updated_at': time.time(),
        })
        atomic(path, row)
    subprocess.run(['python3', str(PIVOT / 'checklist.py'), 'render'],
                   cwd=PIVOT.parents[1], check=True, stdout=subprocess.DEVNULL)
    print('finalized SOLR-14/15/16')


if __name__ == '__main__':
    main()
