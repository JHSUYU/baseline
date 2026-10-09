#!/usr/bin/env python3
"""Seed bounded shallow plans from observed pretarget I/O on the selected client."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import socket

from actor_audit import events
from campaign import LEDGER, STATE, atomic_json, candidate_rows, queue, sync_ledger
from mirror import RECEIPT as MIRROR
from run_native import RUN_ROOT

HERE = Path(__file__).resolve().parent
RECEIPT = HERE / 'shallow-seed-receipt.json'


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def coverage_digest(state: dict) -> str:
    coverage = {name: state[name] for name in
                ('baseline_probes', 'baseline_methods', 'baseline_lines')}
    for kind in ('probes', 'methods', 'lines'):
        coverage['effective_new_' + kind] = sorted({value
            for trial in state['trials'] if trial['effective']
            for value in trial['new_production_' + kind + '_vs_healthy']})
    return digest(canonical(coverage))


def find_pairs(state: dict, mirror: dict) -> list[dict]:
    singleton_evidence = {trial['plan'][0]: trial for trial in state['trials']
                          if len(trial['plan']) == 1
                          and trial['strict_ordered_injection']
                          and trial['selected_target_outcome'] is not None}
    known = set(state['known_plans'])
    counts: Counter[tuple[str, str]] = Counter()
    witnesses: dict[tuple[str, str], str] = {}
    for trial in state['trials']:
        if not trial['effective']:
            continue
        run_id = trial['run_id']
        event_path = RUN_ROOT / run_id / 'events.tsv'
        expected = mirror['runs'][run_id]['sha256']['events.tsv']
        assert digest(event_path.read_bytes()) == expected, run_id
        selectors = list(dict.fromkeys(value
            for _, value in candidate_rows(events(event_path))))
        for index, first in enumerate(selectors):
            if first not in singleton_evidence:
                continue
            for second in selectors[index + 1:]:
                if first == second or '|||'.join((first, second)) in known:
                    continue
                pair = (first, second)
                counts[pair] += 1
                witnesses.setdefault(pair, run_id)
    return [{'plan': list(pair), 'observed_in_effective_runs': count,
             'witness_run_id': witnesses[pair],
             'witness_events_sha256': mirror['runs'][witnesses[pair]]['sha256']['events.tsv'],
             'first_singleton_run_id': singleton_evidence[pair[0]]['run_id'],
             'first_singleton_effective': singleton_evidence[pair[0]]['effective']}
            for pair, count in sorted(counts.items(),
                                      key=lambda item: (
                                          not singleton_evidence[item[0][0]]['effective'],
                                          -item[1], item[0]))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-new-pairs', type=int, default=32)
    args = parser.parse_args()
    assert 0 < args.max_new_pairs <= 32
    state = json.loads(STATE.read_text())
    mirror = json.loads(MIRROR.read_text())
    assert state['inflight'] is None and not state['finished']
    candidates = find_pairs(state, mirror)
    selected = candidates[:args.max_new_pairs]
    if args.dry_run:
        print(json.dumps({'attempts': state['attempts'],
                          'effective': state['effective'],
                          'unseen_pairs': len(candidates), 'selected': selected},
                         sort_keys=True))
        return
    assert socket.gethostname().split('.')[0] == 'node2'
    assert not RECEIPT.exists(), 'one-time seed receipt already exists'
    before = {
        'state_sha256': digest(STATE.read_bytes()),
        'ledger_sha256': digest(LEDGER.read_bytes()),
        'mirror_receipt_sha256': digest(MIRROR.read_bytes()),
        'pre_seed_independent_audit_sha256': digest((HERE / 'final-audit.json').read_bytes()),
        'pending_sha256': digest(canonical(state['pending'])),
        'known_plans_sha256': digest(canonical(state['known_plans'])),
        'trials_sha256': digest(canonical(state['trials'])),
        'coverage_sha256': coverage_digest(state),
        'pending_count': len(state['pending']),
        'known_plan_count': len(state['known_plans']),
    }
    old_pending = list(state['pending'])
    old_known = list(state['known_plans'])
    for entry in selected:
        queue(state, entry['plan'], entry['witness_run_id'])
    added = state['pending'][len(old_pending):]
    assert len(added) == len(selected)
    state['pending'] = added + old_pending
    assert state['known_plans'][:len(old_known)] == old_known
    assert state['pending'][len(added):] == old_pending
    assert digest(canonical(state['trials'])) == before['trials_sha256']
    assert coverage_digest(state) == before['coverage_sha256']
    atomic_json(STATE, state)
    sync_ledger(state)
    after = {
        'state_sha256': digest(STATE.read_bytes()),
        'ledger_sha256': digest(LEDGER.read_bytes()),
        'mirror_receipt_sha256': digest(MIRROR.read_bytes()),
        'pending_sha256': digest(canonical(state['pending'])),
        'known_plans_sha256': digest(canonical(state['known_plans'])),
        'trials_sha256': digest(canonical(state['trials'])),
        'coverage_sha256': coverage_digest(state),
        'pending_count': len(state['pending']),
        'known_plan_count': len(state['known_plans']),
    }
    assert after['trials_sha256'] == before['trials_sha256']
    assert after['coverage_sha256'] == before['coverage_sha256']
    assert after['ledger_sha256'] == before['ledger_sha256']
    assert after['mirror_receipt_sha256'] == before['mirror_receipt_sha256']
    receipt = {
        'schema_version': 1, 'case_id': 'SOLR-18',
        'applied_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'checkpoint_attempts': state['attempts'],
        'checkpoint_effective': state['effective'],
        'next_trial': state['next_trial'],
        'reason': 'Fresh ordered two-fault plans from pretarget I/O observed on the selected live SolrZkClient in effective traces; the first selector as a singleton preserved the selected guard, with effective singletons ranked first.',
        'candidate_count': len(candidates), 'added_count': len(added),
        'added': selected, 'before': before, 'after': after,
        'existing_queue_preserved_in_original_order_after_new_pairs': True,
        'executed_trials_and_coverage_unchanged': True,
    }
    temp = RECEIPT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    temp.replace(RECEIPT)
    print(json.dumps({'attempts': state['attempts'],
                      'effective': state['effective'],
                      'unseen_pairs': len(candidates),
                      'added': len(added),
                      'pending': len(state['pending'])}, sort_keys=True))


if __name__ == '__main__':
    main()
