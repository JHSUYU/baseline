#!/usr/bin/env python3
"""Mirror SOLR-05 source-linked upstream writer checkpoints to its case row."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
import time


CASE = Path(__file__).resolve().parents[1]
STATE = CASE / 'evidence/campaign/state.json'
RESULT = CASE.parent / 'result.json'
LOCK = CASE.parent / '.actor-upstream-sync.lock'
SITE = 'SOLR-05'
EVIDENCE = '.study-repairs/unit-test-pivot/cases/SOLR-05/actor-upstream/evidence/campaign/state.json'


def publish() -> bool:
    if not STATE.is_file():
        return False
    with LOCK.open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        state = json.loads(STATE.read_text())
        result = json.loads(RESULT.read_text())
        if 'actor_v3_register_local' not in result:
            result['actor_v3_register_local'] = {
                key: result.get(key) for key in (
                    'status', 'evidence', 'fault_trials', 'strict_injections',
                    'valid_trials', 'target_after_fault', 'target_exception_candidates',
                    'coverage_gain', 'coverage_methods_gain', 'coverage_branches_gain',
                    'elapsed_seconds', 'stop_reason')}
            result['actor_v3_register_local']['reason'] = (
                'Completed exact replica-host register-local stage; six unique pre-guard '
                'I/O roots were exhausted. Kept separate from upstream writer denominator.')
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
            'status': 'actor_upstream_pending_review' if stopped else 'actor_upstream_running',
            'quality_complete': False,
            'methodology': 'independent_graph_free_overseer_state_writer_replica_zk_coverage',
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
            'bug_mark': 'upstream_writer_candidate_needs_source_review' if candidates else 'none',
            'candidate_disposition': 'pending_upstream_source_review' if candidates else None,
            'reason': ('Overseer writer stage stopped; raw audit and source review pending'
                       if stopped else 'Overseer writer stage running from atomic trial checkpoints'),
            'actor_identity_note': ('The writer must map to a unique Overseer ZK client/reader '
                                    'and exactly one newly added replica; the later selected '
                                    'guard must join that collection/shard/replica/core/target node.'),
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
