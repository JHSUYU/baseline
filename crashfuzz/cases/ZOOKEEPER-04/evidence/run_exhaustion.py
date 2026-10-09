#!/usr/bin/env python3
"""Attempt remaining observed pre-target epoch I/O ordinals and late read retry."""

import json
from pathlib import Path
import subprocess
import sys

import campaign


HERE = Path(__file__).resolve().parent
RUNS = Path('/users/ZhenyuLi/zk04-runs')


def main():
    summary = json.loads(campaign.SUMMARY.read_text())
    trials = summary['trials']
    seed_coverage = campaign.coverage(campaign.SEED / 'coverage.tsv')
    seed_io = set(summary['healthy_io_sites'])
    seed_events = campaign.parse_events(campaign.SEED / 'events.tsv')
    epoch_site = next(e['detail'][0] for e in seed_events if e['kind'] == 'IO'
                      and 'QuorumPeer#readLongFromFile' in e['detail'][0])
    read_site = next(e['detail'][0] for e in seed_events if e['kind'] == 'IO'
                     and 'ClientCnxnSocketNIO#doIO' in e['detail'][0]
                     and '#read(' in e['detail'][0])
    candidates = [('epoch-{:02d}'.format(i), epoch_site, i) for i in range(3, 7)]
    candidates.append(('retry-read-07', read_site, 7))
    for run_id, site, ordinal in candidates:
        run = RUNS / run_id
        if not (run / 'run.txt').exists():
            with (RUNS / (run_id + '-console.log')).open('w') as out:
                subprocess.run([sys.executable, str(HERE / 'run_native.py'), run_id,
                                'testRevalidateCount', site, str(ordinal)],
                               stdout=out, stderr=subprocess.STDOUT)
        row = campaign.analyze(run_id, site, ordinal, seed_coverage, seed_io)
        trials.append(row)
        campaign.save(trials, seed_coverage, seed_io)
        print('{} matched={} applied={} target_after={} throw={} coverage+={} seconds={:.3f}'.format(
            run_id, row['exact_selector_matches'], row['applied_injections'],
            row['target_after_fault'], row['target_throw_after_fault'],
            row['new_coverage_items_vs_seed'], row['elapsed_seconds']), flush=True)
    result = json.loads(campaign.RESULT.read_text())
    result['status'] = 'pending_budget_expansion'
    result['stopping_reason'] = 'All observed pre-target single I/O occurrences are now attempted; await final feedback/sequence equivalence audit.'
    campaign.RESULT.write_text(json.dumps(result, indent=2) + '\n')
    (HERE / 'exhaustion.done').write_text('5 completed\n')


if __name__ == '__main__':
    main()
