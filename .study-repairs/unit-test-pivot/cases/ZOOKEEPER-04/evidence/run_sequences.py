#!/usr/bin/env python3
"""Use I/O feedback to try ordered two-to-four fault sequences."""

import json
import os
from pathlib import Path
import subprocess
import sys

import campaign


HERE = Path(__file__).resolve().parent
RUNS = Path('/users/ZhenyuLi/zk04-runs')


def sequence_result(run_id, plan, seed_coverage, seed_io):
    run = RUNS / run_id
    events = campaign.parse_events(run / 'events.tsv')
    matched = [e for e in events if e['kind'] == 'FAULT_MATCHED']
    applied = [e for e in events if e['kind'] == 'FAULT_APPLIED']
    guard = [e for e in events if e['kind'] == 'TARGET_GUARD']
    throw = [e for e in events if e['kind'] == 'TARGET_THROW']
    io = [e for e in events if e['kind'] == 'IO']
    observed = [e['detail'][0] + '@@' + e['detail'][1] for e in matched]
    expected = [site + '@@' + str(ordinal) for site, ordinal in plan]
    fault_seq = max((e['seq'] for e in applied), default=10**12)
    props = dict(line.split('=', 1) for line in (run / 'run.txt').read_text().splitlines()
                 if '=' in line)
    cov = campaign.coverage(run / 'coverage.tsv')
    return {
        'id': run_id, 'site': ';'.join(expected),
        'label': '+'.join((site.split('#')[-1].split('(')[0] + '#' + str(ordinal))
                         for site, ordinal in plan),
        'hit_ordinal': '+'.join(str(ordinal) for _, ordinal in plan),
        'fault_plan': [{'site': site, 'hit_ordinal': ordinal} for site, ordinal in plan],
        'elapsed_seconds': float(props.get('elapsed_seconds', '0')),
        'junit_exit_code': int(props.get('exit_code', '125')),
        'exact_selector_matches': len(matched), 'applied_injections': len(applied),
        'strict': observed == expected and len(applied) == len(plan),
        'target_seen_anytime': bool(guard),
        'target_after_fault': len(applied) == len(plan)
                              and any(e['seq'] > fault_seq for e in guard),
        'target_guard_entries_after_fault': sum(e['seq'] > fault_seq for e in guard)
                                             if len(applied) == len(plan) else 0,
        'target_throw_after_fault': sum(e['seq'] > fault_seq for e in throw)
                                    if len(applied) == len(plan) else 0,
        'target_throw_anytime': len(throw),
        'new_coverage_items_vs_seed': len(cov - seed_coverage),
        'new_io_sites_vs_seed': sorted({campaign.io_key(e) for e in io} - seed_io),
        'new_coverage_items': sorted(cov - seed_coverage),
        'observed_io_sites': sorted({campaign.io_key(e) for e in io}),
        'junit_symptoms': [], 'bug_mark': 'none',
    }


def main():
    summary = json.loads(campaign.SUMMARY.read_text())
    trials = summary['trials']
    seed_coverage = campaign.coverage(campaign.SEED / 'coverage.tsv')
    seed_io = set(summary['healthy_io_sites'])
    seed_events = campaign.parse_events(campaign.SEED / 'events.tsv')
    write_site = next(e['detail'][0] for e in seed_events if e['kind'] == 'IO'
                      and 'ClientCnxnSocketNIO#doIO' in e['detail'][0]
                      and '#write(' in e['detail'][0])
    read_site = next(e['detail'][0] for e in seed_events if e['kind'] == 'IO'
                     and 'ClientCnxnSocketNIO#doIO' in e['detail'][0]
                     and '#read(' in e['detail'][0])
    # Trial 01 observed a retry at write ordinal 2 before the first target
    # check, and read ordinal 1 before the second target check.
    plans = [
        ('sequence-01b', [(write_site, 1), (write_site, 2)]),
        ('sequence-02b', [(write_site, 1), (read_site, 1)]),
        ('sequence-03b', [(write_site, 1), (write_site, 2), (write_site, 3)]),
        ('sequence-04b', [(write_site, 1), (write_site, 2),
                         (write_site, 3), (write_site, 4)]),
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
        row = sequence_result(run_id, plan, seed_coverage, seed_io)
        trials.append(row)
        campaign.save(trials, seed_coverage, seed_io)
        print('{} matched={}/{} applied={} target_after={} throw={} coverage+={} seconds={:.3f}'.format(
            run_id, row['exact_selector_matches'], len(plan),
            row['applied_injections'], row['target_after_fault'],
            row['target_throw_after_fault'], row['new_coverage_items_vs_seed'],
            row['elapsed_seconds']), flush=True)
    result = json.loads(campaign.RESULT.read_text())
    result['status'] = 'pending_budget_expansion'
    result['stopping_reason'] = 'Twelve seed I/O occurrences and four ordered two-to-four fault plans attempted; continuation audits newly observed I/O occurrences and the 48/4 budget.'
    campaign.RESULT.write_text(json.dumps(result, indent=2) + '\n')
    (HERE / 'sequences.done').write_text('4 completed\n')


if __name__ == '__main__':
    main()
