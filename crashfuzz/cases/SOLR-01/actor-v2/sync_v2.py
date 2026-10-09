#!/usr/bin/env python3
"""Mirror atomic actor-aware trial checkpoints into the one-check table row."""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
STATE = HERE / 'campaign/state.json'
RESULT = CASE / 'result.json'
LOCK = CASE / '.actor-v2-sync.lock'


def publish() -> bool:
    if not STATE.exists():
        return False
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(STATE.read_text())
        result = json.loads(RESULT.read_text())
        trials = state['trials']
        effective = [row for row in trials if row['effective']]
        finished = bool(state.get('stopped'))
        target_throws = sum(row['target_exception'] for row in effective)
        result.update({
            'status': 'actor_v2_pending_review' if finished else 'actor_v2_running',
            'quality_complete': False,
            'methodology': 'independent_graph_free_actor_aware_http_io_coverage_v2',
            'campaign_workspace': 'cases/SOLR-01/actor-v2',
            'evidence': 'crashfuzz/cases/SOLR-01/actor-v2/campaign/state.json',
            'fault_trials': len(trials),
            'strict_injections': sum(row['exact_injection'] for row in trials),
            'fully_applied_trials': sum(row['exact_injection'] for row in trials),
            'valid_trials': len(effective),
            'target_after_fault': len(effective),
            'target_exception_candidates': target_throws,
            'coverage_gain': len(state['seen_coverage']) - len(state['baseline_coverage']),
            'new_io_identities': len(state['seen_families']) - len(state['baseline_families']),
            'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in trials), 3),
            'max_applied_faults': max((row['applied_faults'] for row in trials), default=0),
            'budget': {'max_attempts': state['budget']['max_selected'],
                       'max_faults': state['budget']['max_faults'],
                       'max_valid_trials': state['budget']['effective_trials']},
            'extension_reason': state.get('extension_reason'),
            'bug_mark': 'actor_v2_candidate_needs_source_review' if target_throws else 'none',
            'candidate_disposition': 'pending_v2_source_review' if target_throws else None,
            'actor_identity_note': 'Each applied LISTALIASES point binds the selected provider/client and verifies the actual Jetty nodeName and baseUrl; cross-run selector uses its attempt-relative role.',
            'reason': 'V2 budget reached; raw audit and coverage summary pending' if finished
                      else 'Actor-aware V2 campaign running from atomic trial checkpoints',
        })
        temporary = RESULT.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        temporary.replace(RESULT)
        return finished


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    previous = None
    while True:
        stamp = STATE.stat().st_mtime_ns if STATE.exists() else None
        if stamp != previous:
            done = publish()
            previous = stamp
            if done:
                break
        if args.once:
            break
        time.sleep(3)


if __name__ == '__main__':
    main()
