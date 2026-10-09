#!/usr/bin/env python3
"""Publish audited V2 metrics while retaining the non-credit legacy record."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1]
ROOT = HERE.parents[3]
RESULT = CASE / 'result.json'


def main() -> None:
    calibration = json.loads((HERE / 'calibration-v2.json').read_text())
    campaign = json.loads((HERE / 'campaign/audit-v2.json').read_text())
    coverage = json.loads((HERE / 'campaign/production-coverage-audit-v2.json').read_text())
    archive = json.loads((HERE / 'campaign/raw-trials-v2-receipt.json').read_text())
    if campaign['status'] not in ('budget_complete', 'queue_exhausted'):
        raise RuntimeError('V2 campaign is not terminal')
    if campaign['exact_target_throw_after_fault_trials']:
        raise RuntimeError('exact target exception requires clean replay and source review')
    if campaign['status'] == 'budget_complete' and campaign['effective_trials'] < 80:
        raise RuntimeError('V2 budget_complete before 80 effective trials')
    if campaign['effective_trials'] != 128 or campaign['selected_sequences'] != 129:
        raise RuntimeError('final V2 extension accounting mismatch')
    if coverage['valid_trial_count'] != campaign['effective_trials']:
        raise RuntimeError('production coverage trial set mismatch')
    raw_archive = HERE / 'campaign/raw-trials-v2.tar.zst'
    if hashlib.sha256(raw_archive.read_bytes()).hexdigest() != archive['archive_sha256']:
        raise RuntimeError('raw trial archive hash mismatch')
    result = json.loads(RESULT.read_text())
    if 'legacy_coarse_actor' not in result:
        raise RuntimeError('legacy evidence must be preserved')
    summary = {
        'status': campaign['status'],
        'budget': campaign['budget'],
        'selected_sequences': campaign['selected_sequences'],
        'effective_trials': campaign['effective_trials'],
        'total_junit_attempts': campaign['total_junit_attempts'],
        'strict_injections': campaign['strict_injections'],
        'post_fault_target_reach_trials': campaign['post_fault_target_reach_trials'],
        'passing_junit_trials': campaign['passing_junit_trials'],
        'nonpassing_effective_trials': campaign['nonpassing_effective_trials'],
        'lost_target_sequences': campaign['lost_target_sequences'],
        'exact_target_throw_after_fault_trials': 0,
        'healthy_elapsed_seconds': calibration['healthy_elapsed_seconds'],
        'campaign_elapsed_seconds': campaign['elapsed_junit_seconds'],
        'production_probe_gain': campaign['production_probe_gain'],
        'actor_bound_io_family_gain': campaign['actor_bound_io_family_gain'],
        'production_methods_gain': coverage['new_production_methods'],
        'production_branch_outcomes_gain': coverage['new_production_branch_outcomes'],
        'agent_sha256': calibration['node2_agent_sha256'],
        'original_test_source_sha256': calibration['original_test_source_sha256'],
        'original_test_class_sha256': calibration['original_test_class_sha256'],
        'release_solr_core_jar_sha256': calibration['release_solr_core_jar_sha256'],
        'stable_pre_guard_actor_bound_selectors': calibration['stable_selector_count'],
        'last8_effective_novelty': campaign['last8_effective_novelty'],
        'raw_trial_archive_sha256': archive['archive_sha256'],
        'raw_trial_archive_files': archive['file_count'],
        'raw_trial_archive': 'crashfuzz/cases/SOLR-31/independent/actor-v2/campaign/raw-trials-v2.tar.zst',
        'evidence': 'crashfuzz/cases/SOLR-31/independent/actor-v2/campaign/audit-v2.json',
    }
    result.update(
        actor_v2=summary,
        baseline_seconds=calibration['healthy_elapsed_seconds'],
        elapsed_seconds=campaign['elapsed_junit_seconds'],
        fault_trials=campaign['effective_trials'],
        strict_injections=campaign['effective_trials'],
        post_fault_target_reach_trials=campaign['post_fault_target_reach_trials'],
        target_after_fault=campaign['post_fault_target_reach_trials'],
        target_exception_after_fault_trials=0,
        coverage_gain=campaign['production_probe_gain'],
        io_family_gain=campaign['actor_bound_io_family_gain'],
        production_methods_gain=coverage['new_production_methods'],
        production_branch_outcomes_gain=coverage['new_production_branch_outcomes'],
        quality_complete=True,
        status='quality_complete',
        reason=('Actor-bound original ForceLeader JUnit V2 completed with '
                f'{campaign["effective_trials"]} effective target-preserving trials; '
                'zero exact active-leader guard exceptions. Three target-preserving '
                'trials had later HTTP response timeouts, and one selected sequence '
                'lost the target. This is a bounded ZooKeeper I/O result; legacy '
                'coarse-actor trials remain non-credit.'),
        evidence=summary['evidence'],
        updated_at=time.time(),
    )
    temporary = RESULT.with_name('result.json.v2.tmp')
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    temporary.replace(RESULT)
    subprocess.run(['python3', str(ROOT / 'checklist.py'), 'render'], check=True)
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
