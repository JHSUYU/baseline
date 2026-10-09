#!/usr/bin/env python3
"""Independently recompute ZK13 actor/target receipts and feedback from raw runs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from audit_calibration import one
from calibrate_healthy import AGENT, ROOT, sha
from campaign import CHECKPOINT, LEDGER, candidates, evaluate, selector


def audit(terminal=False):
    checkpoint_bytes = CHECKPOINT.read_bytes()
    state = json.loads(checkpoint_bytes)
    if terminal and state['status'] not in ('budget_complete', 'queue_exhausted', 'attempt_cap'):
        raise RuntimeError('campaign has not reached terminal status')
    if state['inflight']:
        raise RuntimeError('inflight original JUnit trial remains')
    if state.get('feedback_baseline') != 'healthy_union_normalized_io_v3':
        raise RuntimeError('fault feedback did not use normalized I/O families and both healthy seeds')
    if len(state['results']) != state['next_trial'] - 1:
        raise RuntimeError('run IDs or checkpoint selected count differ')
    if state['effective_count'] != sum(item['effective'] for item in state['results']):
        raise RuntimeError('effective denominator differs from completed trials')
    if state['status'] == 'queue_exhausted' and state['pending']:
        raise RuntimeError('queue-exhausted status retains pending plans')
    seeds = [one(name) for name in ('healthy-a', 'healthy-b')]
    if any(seed['status'] != 'pass' for seed in seeds):
        raise RuntimeError('fresh original JUnit calibration failed')
    seed_receipts = [json.loads((ROOT / name / 'run.json').read_text())
                     for name in ('healthy-a', 'healthy-b')]
    stable = {key: seed_receipts[0][key] for key in
              ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
               'classpath_sha256', 'original_source_commit')}
    if stable['agent_sha256'] != sha(AGENT) or any(
            receipt[key] != value for receipt in seed_receipts
            for key, value in stable.items()):
        raise RuntimeError('healthy source, JUnit runner, or agent identity changed')
    coverage = set().union(*(
        set((ROOT / name / 'coverage.tsv').read_text().splitlines())
        for name in ('healthy-a', 'healthy-b')))
    from receipt_validator import parse_events
    families = {x['family'] for name in ('healthy-a', 'healthy-b')
                for x in candidates(parse_events(ROOT / name / 'events.tsv'))}
    rows = []
    for number, stored in enumerate(state['results'], 1):
        run_id = 'trial-{:04d}'.format(number)
        if stored['run_id'] != run_id:
            raise RuntimeError('completed trial IDs are not unique and sequential')
        folder = ROOT / run_id
        receipt = json.loads((folder / 'run.json').read_text())
        if receipt['run_id'] != run_id or receipt['plan'] != stored['plan'] or any(
                receipt[key] != value for key, value in stable.items()):
            raise RuntimeError(run_id + ' original JUnit/source receipt changed')
        recalculated = evaluate(stored, receipt)
        for key, value in recalculated.items():
            if key not in ('coverage', 'mutation_io') and stored.get(key) != value:
                raise RuntimeError(run_id + ' raw actor/target verdict changed: ' + key)
        previous_coverage = coverage.copy()
        previous_families = families.copy()
        if recalculated['effective']:
            coverage.update(recalculated['coverage'])
            families.update(x['family'] for x in recalculated['mutation_io'])
        gain = len(coverage - previous_coverage)
        family_gain = len(families - previous_families)
        if stored['new_coverage_lines'] != gain or stored['new_io_families'] != family_gain:
            raise RuntimeError(run_id + ' coverage/I/O feedback differs from raw events')
        event_rows = parse_events(folder / 'events.tsv')
        matched = [selector(fields) for _, kind, fields in event_rows
                   if kind == 'FAULT_MATCHED']
        applied = [selector(fields) for _, kind, fields in event_rows
                   if kind == 'FAULT_APPLIED']
        exact = matched == stored['plan'] and applied == stored['plan']
        rows.append({'run_id': run_id, 'elapsed_seconds': receipt['elapsed_seconds'],
                     'junit_exit': receipt['exit_code'], 'plan': stored['plan'],
                     'exact': exact, 'effective': stored['effective'],
                     'postfault_target': bool(stored['strict_receipt']),
                     'selected_target_throws': stored['selected_target_throw_count'],
                     'new_coverage_lines': gain, 'new_io_families': family_gain,
                     'invalid_reason': stored['invalid_reason'],
                     'events_sha256': sha(folder / 'events.tsv'),
                     'coverage_sha256': sha(folder / 'coverage.tsv'),
                     'receipt_sha256': sha(folder / 'run.json')})
    if coverage != set(state['seen_coverage']) or families != set(state['seen_families']):
        raise RuntimeError('checkpoint cumulative feedback differs from raw trials')
    ledger = [json.loads(line) for line in LEDGER.read_text().splitlines()]
    if ledger != state['results']:
        raise RuntimeError('append-only trial ledger differs from checkpoint')
    if state['budget_effective'] == 128:
        first_eighty = [x for x in rows if x['effective']][:80]
        if len(first_eighty) != 80 or not any(
                x['new_coverage_lines'] or x['new_io_families']
                for x in first_eighty[-8:]):
            raise RuntimeError('extended budget lacks permitted late novelty')
    healthy_coverage = set().union(*(
        set((ROOT / name / 'coverage.tsv').read_text().splitlines())
        for name in ('healthy-a', 'healthy-b')))
    return {'status': state['status'], 'utc': datetime.now(timezone.utc).isoformat(),
            'checkpoint_sha256': hashlib.sha256(checkpoint_bytes).hexdigest(),
            'agent_sha256': stable['agent_sha256'],
            'original_source_commit': stable['original_source_commit'],
            'selected_attempts': len(rows), 'exact_fault_plans': sum(x['exact'] for x in rows),
            'effective': state['effective_count'], 'effective_budget': state['budget_effective'],
            'max_faults': state['max_faults'], 'pending': len(state['pending']),
            'healthy_seconds': round(sum(x['elapsed_seconds'] for x in seed_receipts), 3),
            'trial_seconds': round(sum(x['elapsed_seconds'] for x in rows), 3),
            'selected_target_throw_events': sum(x['selected_target_throws'] for x in rows),
            'effective_coverage_gain': len(coverage - healthy_coverage),
            'effective_io_family_gain': len(families - {
                x['family'] for name in ('healthy-a', 'healthy-b')
                for x in candidates(parse_events(ROOT / name / 'events.tsv'))}),
            'healthy': [{'run_id': x, 'events_sha256': sha(ROOT / x / 'events.tsv'),
                         'coverage_sha256': sha(ROOT / x / 'coverage.tsv')}
                        for x in ('healthy-a', 'healthy-b')],
            'trials': rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--terminal', action='store_true')
    parser.add_argument('--write', type=Path)
    args = parser.parse_args()
    result = audit(args.terminal)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'selected_attempts',
                                             'exact_fault_plans', 'effective',
                                             'pending', 'effective_coverage_gain')},
                     sort_keys=True))


if __name__ == '__main__':
    main()
