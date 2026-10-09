#!/usr/bin/env python3
"""Probe write ordinals exposed before a later target by prior fault feedback."""

import json
import os
from pathlib import Path
import subprocess
import sys

import campaign
import run_sequences


HERE = Path(__file__).resolve().parent
RUNS = Path('/users/ZhenyuLi/zk04-runs')


def main():
    summary = json.loads(campaign.SUMMARY.read_text())
    trials = summary['trials']
    seed_cov = campaign.coverage(campaign.SEED / 'coverage.tsv')
    seed_io = set(summary['healthy_io_sites'])
    seed = campaign.parse_events(campaign.SEED / 'events.tsv')
    write = next(e['detail'][0] for e in seed if e['kind'] == 'IO'
                 and 'ClientCnxnSocketNIO#doIO' in e['detail'][0]
                 and '#write(' in e['detail'][0])
    plans = [
        ('feedback-01', [(write, i) for i in (1, 2, 3, 5)]),
        ('feedback-02', [(write, i) for i in (1, 2, 4, 5)]),
    ]
    for run_id, plan in plans:
        run = RUNS / run_id
        if not (run / 'run.txt').exists():
            env = os.environ.copy()
            env['ZK04_FAULT_PLAN'] = '|||'.join(site + '@@' + str(ordinal)
                                                for site, ordinal in plan)
            with (RUNS / (run_id + '-console.log')).open('w') as out:
                subprocess.run([sys.executable, str(HERE / 'run_native.py'), run_id],
                               env=env, stdout=out, stderr=subprocess.STDOUT)
        row = run_sequences.sequence_result(run_id, plan, seed_cov, seed_io)
        trials.append(row)
        campaign.save(trials, seed_cov, seed_io)
        print('{} matched={}/{} applied={} target_after={} throw={} coverage+={} seconds={:.3f}'.format(
            run_id, row['exact_selector_matches'], len(plan),
            row['applied_injections'], row['target_after_fault'],
            row['target_throw_after_fault'], row['new_coverage_items_vs_seed'],
            row['elapsed_seconds']), flush=True)
    result = json.loads(campaign.RESULT.read_text())
    result['status'] = 'pending_budget_expansion'
    result['stopping_reason'] = 'Feedback sequences complete; final pre-target occurrence feasibility audit pending.'
    campaign.RESULT.write_text(json.dumps(result, indent=2) + '\n')
    (HERE / 'feedback-sequences.done').write_text('2 completed\n')


if __name__ == '__main__':
    main()
