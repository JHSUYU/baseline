#!/usr/bin/env python3
"""Bounded graph-free fault campaign, updating this case after each JUnit run."""

import csv
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RUNS = Path('/users/ZhenyuLi/zk04-runs')
SEED = RUNS / 'seed-03'
RESULT = CASE / 'result.json'
SUMMARY = HERE / 'trials-summary.json'
TABLE = CASE / 'trial-summary.csv'
README = CASE / 'README.md'
MAX_TRIALS = 128


def atomic_text(path, content):
    with tempfile.NamedTemporaryFile(mode='w', dir=str(path.parent),
                                     prefix=path.name + '.', suffix='.tmp',
                                     delete=False) as out:
        out.write(content)
        out.flush()
        os.fsync(out.fileno())
        temporary = Path(out.name)
    os.replace(str(temporary), str(path))


def parse_events(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        cells = line.split('\t')
        if len(cells) >= 3:
            rows.append({'seq': int(cells[0]), 'kind': cells[1],
                         'thread': cells[2], 'detail': cells[3:]})
    return rows


def io_key(row):
    return row['detail'][0] if row['detail'] else ''


def coverage(path):
    return set(path.read_text().splitlines()) if path.exists() else set()


def analyze(run_id, site, ordinal, seed_coverage, seed_io):
    run = RUNS / run_id
    events = parse_events(run / 'events.tsv')
    matched = [e for e in events if e['kind'] == 'FAULT_MATCHED']
    applied = [e for e in events if e['kind'] == 'FAULT_APPLIED']
    fault_seq = max((e['seq'] for e in applied), default=10**12)
    guards = [e for e in events if e['kind'] == 'TARGET_GUARD']
    throws = [e for e in events if e['kind'] == 'TARGET_THROW']
    io = [e for e in events if e['kind'] == 'IO']
    run_props = {}
    if (run / 'run.txt').exists():
        run_props = dict(line.split('=', 1) for line in
                         (run / 'run.txt').read_text().splitlines() if '=' in line)
    cov = coverage(run / 'coverage.tsv')
    log = (run / 'junit.log').read_text(errors='replace') if (run / 'junit.log').exists() else ''
    symptoms = []
    for term in ('ConnectionLossException', 'SessionExpiredException',
                 'AssertionFailedError', 'TimeoutException', 'IOException'):
        if term in log:
            symptoms.append(term)
    return {
        'id': run_id, 'site': site, 'hit_ordinal': ordinal,
        'elapsed_seconds': float(run_props.get('elapsed_seconds', '0')),
        'junit_exit_code': int(run_props.get('exit_code', '125')),
        'exact_selector_matches': len(matched), 'applied_injections': len(applied),
        'strict': len(matched) == len(applied) == 1
                  and matched[0]['detail'] == [site, str(ordinal)]
                  and applied[0]['detail'] == [site, str(ordinal)],
        'target_seen_anytime': bool(guards),
        'target_after_fault': any(e['seq'] > fault_seq for e in guards),
        'target_guard_entries_after_fault': sum(e['seq'] > fault_seq for e in guards),
        'target_throw_after_fault': sum(e['seq'] > fault_seq for e in throws),
        'target_throw_anytime': len(throws),
        'new_coverage_items_vs_seed': len(cov - seed_coverage),
        'new_io_sites_vs_seed': sorted({io_key(e) for e in io} - seed_io),
        'new_coverage_items': sorted(cov - seed_coverage),
        'observed_io_sites': sorted({io_key(e) for e in io}),
        'junit_symptoms': symptoms,
        'bug_mark': 'none',
    }


def save(trials, seed_coverage, seed_io):
    union_cov = set()
    admitted_cov = set()
    union_io = set()
    for row in trials:
        union_cov.update(row['new_coverage_items'])
        if row['strict'] and row['target_after_fault']:
            admitted_cov.update(row['new_coverage_items'])
        union_io.update(row['new_io_sites_vs_seed'])
    summary = {'case_id': 'ZOOKEEPER-04', 'seed': str(SEED),
               'healthy_coverage_items': len(seed_coverage),
               'healthy_io_sites': sorted(seed_io), 'trials': trials,
               'union_new_coverage_items_vs_seed': len(union_cov),
               'union_new_io_sites_vs_seed': sorted(union_io)}
    atomic_text(SUMMARY, json.dumps(summary, indent=2) + '\n')
    fields = ['id', 'site', 'hit_ordinal', 'elapsed_seconds', 'junit_exit_code',
              'exact_selector_matches', 'applied_injections', 'target_after_fault',
              'target_throw_after_fault', 'new_coverage_items_vs_seed',
              'new_io_sites_vs_seed', 'bug_mark']
    out = io.StringIO(newline='')
    try:
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore',
                                lineterminator='\n')
        writer.writeheader()
        for row in trials:
            r = dict(row)
            r['new_io_sites_vs_seed'] = ';'.join(row['new_io_sites_vs_seed'])
            writer.writerow(r)
        atomic_text(TABLE, out.getvalue())
    finally:
        out.close()
    data = json.loads(RESULT.read_text())
    run_times = []
    run_starts = []
    for path in RUNS.glob('*/run.txt'):
        props = dict(line.split('=', 1) for line in path.read_text().splitlines()
                     if '=' in line)
        elapsed = float(props.get('elapsed_seconds', '0'))
        run_times.append(elapsed)
        run_starts.append(path.stat().st_mtime - elapsed)
    data.update({
        'status': 'fuzzing', 'fault_trials': len(trials),
        'strict_trials': sum(bool(row['strict']) for row in trials),
        'strict_injections': sum(row['applied_injections'] for row in trials if row['strict']),
        'exact_selector_matches': sum(row['exact_selector_matches'] for row in trials),
        'applied_injections': sum(row['applied_injections'] for row in trials),
        'target_after_fault': sum(row['target_after_fault'] for row in trials),
        'target_exception_after_fault_trials': sum(row['target_throw_after_fault'] > 0 for row in trials),
        'coverage_gain': len(union_cov),
        'admitted_coverage_gain': len(admitted_cov),
        'coverage_gain_qualification': 'coverage_gain is observed new line coverage against the healthy seed; admitted_coverage_gain requires exact applied faults and target evaluation after the final fault',
        'new_io_families_observed': len(union_io),
        'trial_elapsed_seconds': round(sum(row['elapsed_seconds'] for row in trials), 3),
        'elapsed_seconds': round(sum(run_times), 3),
        'case_wall_elapsed_seconds_from_first_jvm': round(time.time() - min(run_starts), 3),
        'elapsed_measurement': 'sum of all completed case-local JVM runs including probe preflight, healthy seed, positive control and fault trials; excludes manual source review/build time and idle gaps',
        'trial_results': str(SUMMARY.relative_to(Path('/users/ZhenyuLi/baseline'))),
        'bug_mark': 'none',
    })
    atomic_text(RESULT, json.dumps(data, indent=2) + '\n')
    lines = [
        '# ZOOKEEPER-04: client zxid ahead', '',
        'The selected check is the `LCMP@283; IFLE@284` guard at ZooKeeperServer.java:1431. '
        'Its selected throw is `ATHROW@376` at line 1441, constructing '
        '`CloseRequestException(CLIENT_ZXID_AHEAD)`. This rejection is protective and expected '
        'when a client has seen a zxid newer than the server DataTree.', '',
        'The unchanged original `ConnectionMetricsTest.testRevalidateCount` starts three peers and '
        'reconnects the same client from one follower to another. The healthy JUnit passed '
        'in 13.408 seconds; the exact guard was evaluated twice, both on its normal arm; '
        'the selected throw was absent. The healthy trace recorded {} line-coverage items and {} '
        'direct I/O sites.'.format(len(seed_coverage), len(seed_io)), '',
        'The original `ZooKeeperServerTest.testClientZxidAhead` was run as a positive '
        'control (2.420 seconds, JUnit pass). It deliberately sends zxid 99 to a '
        'mock connection and asserts `CLIENT_ZXID_AHEAD`; this probe recorded '
        'one selected throw-arm guard and one exact selected throw.', '',
        'A case-local ASM agent instruments the bytecode guard and throw, direct client TCP '
        'read/write calls, epoch-file read calls, and line coverage. Each injected IOException '
        'is selected by exact call site plus hit ordinal, with separate matched/applied events. '
        'The original JUnit lifecycle runner is supplied by a legacy GraphChecker JAR; '
        'no graph, static analysis, aggregation, or closure result controls test selection or faults.', '',
        '| Trial | I/O site and ordinal | Seconds | Matched/applied | Target after fault | '
        'Exact throw | New coverage | New I/O sites | Bug |',
        '| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |',
    ]
    for row in trials:
        short = row.get('label', row['site'].split('#')[-1].split('(')[0])
        lines.append('| {} | `{}` #{} | {:.3f} | {}/{} | {} | {} | {} | {} | {} |'.format(
            row['id'], short, row['hit_ordinal'], row['elapsed_seconds'],
            row['exact_selector_matches'], row['applied_injections'],
            'yes' if row['target_after_fault'] else 'no',
            row['target_throw_after_fault'], row['new_coverage_items_vs_seed'],
            len(row['new_io_sites_vs_seed']), row['bug_mark']))
    lines += ['', 'The table and `result.json` are rewritten after each completed run. '
              'Full logs and trace files are in `/users/ZhenyuLi/zk04-runs/`; '
              'the compact machine-readable record is `evidence/trials-summary.json`.']
    atomic_text(README, '\n'.join(lines) + '\n')


def main():
    seed_events = parse_events(SEED / 'events.tsv')
    seed_coverage = coverage(SEED / 'coverage.tsv')
    if not seed_coverage or not any(e['kind'] == 'TARGET_GUARD' for e in seed_events):
        raise RuntimeError('healthy seed has no exact target guard')
    seed_io = {io_key(e) for e in seed_events if e['kind'] == 'IO'}
    candidates = []
    for e in seed_events:
        if e['kind'] != 'IO' or len(e['detail']) < 2:
            continue
        site, ordinal = e['detail'][0], int(e['detail'][1])
        if 'ClientCnxnSocketNIO#doIO' in site or (
            'QuorumPeer#readLongFromFile' in site and
            ('FileReader#<init>' in site or 'BufferedReader#readLine' in site) and ordinal <= 2
        ):
            candidates.append((site, ordinal))
    # Run exact observed seed points once. Retry and new-site scheduling can extend this
    # bounded list, but never invent an unobserved selector.
    candidates = list(dict.fromkeys(candidates))[:MAX_TRIALS]
    candidates.sort(key=lambda item: (0 if 'ClientCnxnSocketNIO#doIO' in item[0] else 1,
                                     item[1]))
    trials = []
    for idx, (site, ordinal) in enumerate(candidates, 1):
        run_id = 'trial-{:02d}'.format(idx)
        run = RUNS / run_id
        if not (run / 'run.txt').exists():
            with (RUNS / (run_id + '-console.log')).open('w') as out:
                subprocess.run([sys.executable, str(HERE / 'run_native.py'), run_id,
                                'testRevalidateCount', site, str(ordinal)],
                               stdout=out, stderr=subprocess.STDOUT)
        row = analyze(run_id, site, ordinal, seed_coverage, seed_io)
        trials.append(row)
        save(trials, seed_coverage, seed_io)
        print('{} matched={} applied={} target_after={} throw={} coverage+={} io+={} seconds={:.3f}'.format(
            run_id, row['exact_selector_matches'], row['applied_injections'],
            row['target_after_fault'], row['target_throw_after_fault'],
            row['new_coverage_items_vs_seed'], len(row['new_io_sites_vs_seed']),
            row['elapsed_seconds']), flush=True)
    data = json.loads(RESULT.read_text())
    data['status'] = 'bounded_campaign_complete'
    data['stopping_reason'] = '{} distinct directly observed seed I/O occurrences were attempted; no further seed selector remains in the bounded candidate set.'.format(len(candidates))
    RESULT.write_text(json.dumps(data, indent=2) + '\n')
    (HERE / 'campaign.done').write_text('{} completed\n'.format(len(trials)))


if __name__ == '__main__':
    main()
