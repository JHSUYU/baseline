#!/usr/bin/env python3
"""Mirror SOLR-05 relative-replica actor checkpoints to its one-check row."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
import time


CASE = Path(__file__).resolve().parents[1]
STATE = CASE / 'evidence/campaign/state.json'
RESULT = CASE.parent / 'result.json'
LOCK = CASE.parent / '.actor-v3-sync.lock'
SITE = 'SOLR-05'
EVIDENCE = 'crashfuzz/cases/SOLR-05/actor-v3/evidence/campaign/state.json'


def publish() -> bool:
    if not STATE.is_file():
        return False
    with LOCK.open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        state = json.loads(STATE.read_text())
        result = json.loads(RESULT.read_text())
        if 'legacy_actor_v2_physical_role' not in result:
            result['legacy_actor_v2_physical_role'] = {
                key: result.get(key) for key in (
                    'status', 'evidence', 'fault_trials', 'strict_injections',
                    'valid_trials', 'target_after_fault', 'target_exception_candidates',
                    'coverage_gain', 'coverage_methods_gain', 'coverage_branches_gain',
                    'elapsed_seconds', 'stop_reason')}
            result['legacy_actor_v2_physical_role']['reason'] = (
                'Physical Jetty role changes across original JUnit runs; historical '
                'strict trials are retained but excluded from V3 denominator.')
        healthy = json.loads((CASE / 'evidence/healthy-summary.json').read_text())
        trials = state['trials']
        progress = state['site_progress'][SITE]
        valid = [trial for trial in trials if trial['strict'] and
                 trial['target_after_fault'][SITE]]
        candidates = sum(trial['target_exception'][SITE] for trial in valid)
        stopped = progress['stop_reason'] != 'running'
        healthy_branches = state['healthy_branches']
        seen_branches = state['seen_branches'][SITE]
        branch_gain = sum(max(0, count - healthy_branches.get(method, 0))
                          for method, count in seen_branches.items())
        result.update({
            'status': 'actor_v3_pending_review' if stopped else 'actor_v3_running',
            'quality_complete': False,
            'methodology': 'independent_graph_free_relative_replica_host_zk_io_coverage_v3',
            'evidence': EVIDENCE,
            'healthy_target_checks': state['healthy_target_checks'][SITE],
            'healthy_actor_target_checks_per_run': [
                item['target_counts'][SITE] for item in healthy['actor_instrumented_junit']],
            'fault_trials': len(trials),
            'strict_injections': sum(trial['strict'] for trial in trials),
            'fully_applied_trials': sum(trial['strict'] for trial in trials),
            'valid_trials': len(valid),
            'eligible_feedback_trials': len(valid),
            'target_after_fault': len(valid),
            'target_lost_identity_mismatch': sum(
                trial['target_lost_identity_mismatch'][SITE] for trial in trials),
            'target_exception_candidates': candidates,
            'target_guard_triggered': candidates > 0,
            'coverage_gain': len(state['seen_coverage'][SITE]) -
                len(state['healthy_coverage']),
            'coverage_methods_gain': len(state['seen_methods'][SITE]) -
                len(state['healthy_methods']),
            'coverage_branches_gain': branch_gain,
            'new_io_identities': len(state['seen_io_families'][SITE]) -
                len(state['healthy_io_families']),
            'elapsed_seconds': round(state['elapsed_seconds'], 3),
            'max_applied_faults': max((trial['faults_applied'] for trial in trials),
                                      default=0),
            'budget': {'max_trials': progress['goal'],
                       'max_attempts': state['budget']['max_attempts'],
                       'max_faults': state['budget']['max_faults']},
            'stop_reason': progress['stop_reason'],
            'bug_mark': 'actor_v3_candidate_needs_source_review' if candidates else 'none',
            'candidate_disposition': 'pending_v3_source_review' if candidates else None,
            'reason': ('Relative-replica V3 budget stopped; raw audit and source review pending'
                       if stopped else 'Relative-replica V3 running from atomic trial checkpoints'),
            'actor_identity_note': ('Cross-run selector uses stable collection/shard/replica/core. '
                                    'Each run resolves its unique Jetty role, SolrZkClient, '
                                    'ZkStateReader; post-fault guard must use those same objects.'),
        })
        temporary = RESULT.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        temporary.replace(RESULT)
        return stopped


def main() -> None:
    previous = None
    while True:
        stamp = STATE.stat().st_mtime_ns if STATE.exists() else None
        if stamp != previous:
            done = publish()
            previous = stamp
            if done:
                break
        time.sleep(3)


if __name__ == '__main__':
    main()
