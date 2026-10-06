#!/usr/bin/env python3
"""Resume the saved ledger with only newly authorized 5–6 fault sequences."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import campaign
import run_sequences


HERE = Path(__file__).resolve().parent
RUNS = Path('/users/ZhenyuLi/zk04-runs')
WRITE = next(e['detail'][0] for e in campaign.parse_events(campaign.SEED / 'events.tsv')
             if e['kind'] == 'IO' and 'ClientCnxnSocketNIO#doIO' in e['detail'][0]
             and '#write(' in e['detail'][0])


def selected_plan(which):
    if which == 'five':
        return 'budget5-01b', [(WRITE, i) for i in (1, 2, 3, 4, 6)]
    if which == 'six':
        precursor = campaign.parse_events(RUNS / 'budget5-01b' / 'events.tsv')
        seventh = [e for e in precursor if e['kind'] == 'IO'
                   and e['detail'] == [WRITE, '7']]
        guards = [e['seq'] for e in precursor if e['kind'] == 'TARGET_GUARD']
        if not seventh or not any(g > seventh[0]['seq'] for g in guards):
            raise RuntimeError('write ordinal 7 is not observed before a later target in the 5-fault trace')
        return 'budget6-01', [(WRITE, i) for i in (1, 2, 3, 4, 6, 7)]
    raise ValueError(which)


def main():
    which = sys.argv[1]
    run_id, plan = selected_plan(which)
    run = RUNS / run_id
    summary = json.loads(campaign.SUMMARY.read_text())
    if any(row['id'] == run_id for row in summary['trials']):
        raise RuntimeError('trial already in checkpoint: ' + run_id)
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
    row['fault_budget'] = 6
    summary['trials'].append(row)
    campaign.save(summary['trials'], seed_cov, seed_io)
    data = json.loads(campaign.RESULT.read_text())
    data['max_faults_per_trial'] = 6
    data['fault_budget_current'] = 6
    data['new_budget_runner'] = str(HERE / 'runner/original-junit-runner.jar')
    data['new_budget_graphchecker_loaded'] = False
    campaign.atomic_text(campaign.RESULT, json.dumps(data, indent=2) + '\n')
    provenance = {
        'source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
        'runner': str(HERE / 'runner/original-junit-runner.jar'),
        'runner_sha256': hashlib.sha256((HERE / 'runner/original-junit-runner.jar').read_bytes()).hexdigest(),
        'agent': str(HERE / 'agent/audit-agent.jar'),
        'agent_sha256': hashlib.sha256((HERE / 'agent/audit-agent.jar').read_bytes()).hexdigest(),
        'graphchecker_jar_on_new_budget_classpath': False,
        'graphchecker_skeleton_read_by_agent': False,
        'methodology': 'original JUnit Platform method + case-local ASM bytecode probes + exact ordered IOException selectors',
        'historical_25_trial_runner_limit': 'Earlier runs used a GraphChecker JAR solely for JUnit lifecycle; this limitation remains documented separately.',
    }
    campaign.atomic_text(HERE / 'provenance-6fault.json', json.dumps(provenance, indent=2) + '\n')
    print('{} matched={}/{} applied={} target_after={} throw={} coverage+={} seconds={:.3f} junit={}'.format(
        run_id, row['exact_selector_matches'], len(plan), row['applied_injections'],
        row['target_after_fault'], row['target_throw_after_fault'],
        row['new_coverage_items_vs_seed'], row['elapsed_seconds'],
        row['junit_exit_code']), flush=True)


if __name__ == '__main__':
    main()
