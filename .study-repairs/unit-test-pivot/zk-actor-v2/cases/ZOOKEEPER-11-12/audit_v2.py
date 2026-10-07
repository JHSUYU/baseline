#!/usr/bin/env python3
"""Recheck every completed original JUnit receipt and prepare per-check results."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from build_adapter import sha
from calibrate_v2 import CASE, CHECKS, ROOT, SEEDS, rows
from campaign_v2 import (STATE, atomic, audit_actors, selected_target,
                         strict_plan, verify_state)


def audit(terminal=False):
    state = json.loads(STATE.read_text())
    verify_state(state)
    if terminal and (state['inflight'] is not None or state['status'] not in
                     ('complete', 'selected_cap', 'queue_exhausted')):
        raise RuntimeError('campaign is not at a terminal completed boundary')
    peer = state['first_server_sid']
    if peer != '0':
        raise RuntimeError('selected firstServer peer changed')
    healthy_coverage = set()
    healthy_seconds = 0.0
    seed_receipts = []
    source_commit = None
    for name in SEEDS:
        folder = ROOT / name
        receipt = json.loads((folder / 'run.json').read_text())
        if receipt['exit_code'] != 0 or receipt['plan'] or \
                receipt['agent_sha256'] != state['agent_sha256']:
            raise RuntimeError(name + ' healthy receipt changed')
        if source_commit is None:
            source_commit = receipt['original_source_commit']
        elif receipt['original_source_commit'] != source_commit:
            raise RuntimeError('healthy source revision changed')
        healthy_coverage.update((folder / 'coverage.tsv').read_text().splitlines())
        healthy_seconds += receipt['elapsed_seconds']
        seed_receipts.append({'run_id': name, 'trace_sha256': sha(folder / 'events.tsv'),
                              'coverage_sha256': sha(folder / 'coverage.tsv'),
                              'elapsed_seconds': receipt['elapsed_seconds']})
    cumulative_coverage = set(healthy_coverage)
    audited = []
    for result in state['results']:
        run_id = result['run_id']
        folder = ROOT / run_id
        receipt = json.loads((folder / 'run.json').read_text())
        if receipt['run_id'] != run_id or receipt['plan'] != result['plan'] or \
                receipt['agent_sha256'] != state['agent_sha256'] or \
                receipt['elapsed_seconds'] != result['elapsed_seconds'] or \
                receipt['exit_code'] != result['junit_exit'] or \
                receipt['original_source_commit'] != source_commit:
            raise RuntimeError(run_id + ' original JUnit receipt disagrees with checkpoint')
        trace = rows(folder / 'events.tsv')
        actor = audit_actors(trace)
        strict, reason = strict_plan(trace, result['plan'])
        if actor != result['actor_audit'] or strict != result['strict_injection'] or \
                reason != result['invalid_reason']:
            raise RuntimeError(run_id + ' raw actor or exact plan audit changed')
        applied = [seq for seq, kind, _ in trace if kind == 'FAULT_APPLIED']
        last = max(applied, default=0)
        if len(applied) != result['applied_faults']:
            raise RuntimeError(run_id + ' applied fault count changed')
        for case, check in CHECKS.items():
            guarded = selected_target(trace, case, peer, last) if strict else []
            thrown = [(seq, fields) for seq, kind, fields in trace
                      if kind == 'TARGET_THROW' and seq > last and len(fields) >= 5
                      and fields[0] == check and fields[1] == 'peer:' + peer
                      and fields[2] == 'firstServer' and fields[3] == peer]
            recorded = result['case_results'][case]
            if recorded['effective'] != (strict and bool(guarded)) or \
                    recorded['postfault_guards'] != len(guarded) or \
                    recorded['target_throws'] != (len(thrown) if strict else 0):
                raise RuntimeError(run_id + ' selected target receipts changed for ' + case)
        effective_any = any(v['effective'] for v in result['case_results'].values())
        if effective_any:
            current = set((folder / 'coverage.tsv').read_text().splitlines())
            gain = len(current - cumulative_coverage)
            if gain != result['new_coverage_lines']:
                raise RuntimeError(run_id + ' coverage feedback changed')
            cumulative_coverage.update(current)
        elif result['new_coverage_lines'] or result['new_io_families']:
            raise RuntimeError(run_id + ' target-lost trial contaminated feedback')
        audited.append({'run_id': run_id, 'case': result['target_case'],
                        'elapsed_seconds': result['elapsed_seconds'],
                        'fault_depth': len(result['plan']),
                        'exact': strict, 'applied_faults': len(applied),
                        'junit_exit': result['junit_exit'],
                        'new_coverage_lines': result['new_coverage_lines'],
                        'new_io_families': result['new_io_families'],
                        'cases': result['case_results'],
                        'events_sha256': sha(folder / 'events.tsv'),
                        'coverage_sha256': sha(folder / 'coverage.tsv'),
                        'receipt_sha256': sha(folder / 'run.json')})
    if cumulative_coverage != set(state['seen_coverage']):
        raise RuntimeError('cumulative effective coverage differs from checkpoint')
    interrupted = state['selected_count'] - len(audited) - int(state['inflight'] is not None)
    if interrupted < 0:
        raise RuntimeError('completed and inflight runs exceed selected count')
    archived = sorted((ROOT / 'interrupted').glob('trial-*')) \
        if (ROOT / 'interrupted').is_dir() else []
    if len(archived) != interrupted:
        raise RuntimeError('interrupted selection count differs from archived receipts')
    cases = {}
    for case in CHECKS:
        effective = [row for row in audited if row['cases'][case]['effective']]
        budget = state['budgets'][case]
        if len(effective) != budget['effective_count']:
            raise RuntimeError(case + ' effective budget disagrees with raw receipts')
        recent = effective[-8:]
        novelty = any(row['new_coverage_lines'] or row['new_io_families'] for row in recent)
        if budget['extension_decided'] and budget['effective_target'] == 128 and \
                not (len(recent) == 8 and novelty):
            raise RuntimeError(case + ' extension lacks final-eight novelty')
        cases[case] = {
            'effective': len(effective),
            'effective_target': budget['effective_target'],
            'max_faults': budget['max_faults'],
            'extension_decided': budget['extension_decided'],
            'final_eight_effective_novelty': novelty if len(recent) == 8 else None,
            'selected_target_throw_trials': sum(bool(row['cases'][case]['target_throws'])
                                               for row in audited),
            'selected_target_throw_events': sum(row['cases'][case]['target_throws']
                                               for row in audited),
            'postfault_guard_events': sum(row['cases'][case]['postfault_guards']
                                         for row in audited),
            'effective_trial_seconds': round(sum(row['elapsed_seconds'] for row in effective), 3),
        }
    return {
        'utc': datetime.now(timezone.utc).isoformat(),
        'status': state['status'], 'selected': state['selected_count'],
        'completed': len(audited),
        'inflight': None if state['inflight'] is None else state['inflight']['run_id'],
        'interrupted': interrupted,
        'original_source_commit': source_commit,
        'agent_sha256': state['agent_sha256'],
        'script_hashes': state['script_hashes'],
        'calibration_sha256': state['calibration_sha256'],
        'checkpoint_sha256_at_audit': sha(STATE),
        'healthy': seed_receipts,
        'healthy_elapsed_seconds': round(healthy_seconds, 3),
        'trial_elapsed_seconds': round(sum(row['elapsed_seconds'] for row in audited), 3),
        'strict_injection_trials': sum(row['exact'] for row in audited),
        'junit_nonzero_trials': sum(row['junit_exit'] != 0 for row in audited),
        'max_fault_depth_attempted': max((row['fault_depth'] for row in audited), default=0),
        'effective_coverage_lines': len(cumulative_coverage),
        'healthy_coverage_lines': len(healthy_coverage),
        'effective_coverage_gain': len(cumulative_coverage - healthy_coverage),
        'cases': cases,
        'trials': audited,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--terminal', action='store_true')
    parser.add_argument('--write', type=Path, help='write full audit JSON to this path')
    args = parser.parse_args()
    result = audit(args.terminal)
    if args.write:
        atomic(args.write, result)
    print(json.dumps({key: result[key] for key in ('status', 'selected', 'completed',
                                                    'inflight', 'cases')}, sort_keys=True))


if __name__ == '__main__':
    main()
