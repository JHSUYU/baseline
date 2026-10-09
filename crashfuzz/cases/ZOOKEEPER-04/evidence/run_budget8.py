#!/usr/bin/env python3
"""Resume saved ledger with feedback-selected 7–8 fault sequences only."""

import json
import os
from pathlib import Path
import subprocess
import sys

import campaign
import run_sequences
from run_budget6 import WRITE


HERE = Path(__file__).resolve().parent
RUNS = Path('/users/ZhenyuLi/zk04-runs')


def choose(which):
    if which == 'seven':
        precursor_id, run_id, prefix, ordinal = (
            'budget6-01', 'budget7-01', (1, 2, 3, 4, 6, 7), 8)
    elif which == 'eight':
        precursor_id, run_id, prefix, ordinal = (
            'budget7-01', 'budget8-01', (1, 2, 3, 4, 6, 7, 8), 9)
    else:
        raise ValueError(which)
    events = campaign.parse_events(RUNS / precursor_id / 'events.tsv')
    candidates = [e for e in events if e['kind'] == 'IO'
                  and e['detail'] == [WRITE, str(ordinal)]]
    guards = [e['seq'] for e in events if e['kind'] == 'TARGET_GUARD']
    if not candidates or not any(seq > candidates[0]['seq'] for seq in guards):
        raise RuntimeError('{}: write ordinal {} lacks a later target in {}'.format(
            run_id, ordinal, precursor_id))
    return run_id, [(WRITE, i) for i in prefix + (ordinal,)]


def main():
    run_id, plan = choose(sys.argv[1])
    summary = json.loads(campaign.SUMMARY.read_text())
    if any(row['id'] == run_id for row in summary['trials']):
        raise RuntimeError('already in trial ledger: ' + run_id)
    run = RUNS / run_id
    if not (run / 'run.txt').exists():
        env = os.environ.copy()
        env['ZK04_PLAIN_JUNIT'] = '1'
        env['ZK04_FAULT_PLAN'] = '|||'.join(site + '@@' + str(ordinal)
                                            for site, ordinal in plan)
        with (RUNS / (run_id + '-console.log')).open('w') as out:
            subprocess.run([sys.executable, str(HERE / 'run_native.py'), run_id],
                           env=env, stdout=out, stderr=subprocess.STDOUT)
    seed_cov = campaign.coverage(campaign.SEED / 'coverage.tsv')
    seed_io = set(summary['healthy_io_sites'])
    row = run_sequences.sequence_result(run_id, plan, seed_cov, seed_io)
    row['runner'] = 'zk04.OriginalJUnitRunner via JUnit Platform Launcher 1.6.2'
    row['fault_budget'] = 8
    summary['trials'].append(row)
    campaign.save(summary['trials'], seed_cov, seed_io)
    data = json.loads(campaign.RESULT.read_text())
    data['max_faults_per_trial'] = 8
    data['fault_budget_current'] = 8
    campaign.atomic_text(campaign.RESULT, json.dumps(data, indent=2) + '\n')
    print('{} matched={}/{} applied={} target_after={} throw={} coverage+={} seconds={:.3f} junit={}'.format(
        run_id, row['exact_selector_matches'], len(plan), row['applied_injections'],
        row['target_after_fault'], row['target_throw_after_fault'],
        row['new_coverage_items_vs_seed'], row['elapsed_seconds'],
        row['junit_exit_code']), flush=True)


if __name__ == '__main__':
    main()
