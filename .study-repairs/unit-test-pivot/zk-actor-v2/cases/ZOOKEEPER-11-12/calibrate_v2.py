#!/usr/bin/env python3
"""Audit two fresh original JUnit cluster seeds; --run requires an assigned slot."""

import argparse
import json
from pathlib import Path

from build_adapter import BUILD, sha
from run_v2 import AGENT, CASE, ROOT, RUNNER, run, verify_build

CHECKS = {
    'ZOOKEEPER-11': 'ZOOKEEPER-11:QuorumPeer.loadDataBase:1169:currentEpoch.tmp.exists',
    'ZOOKEEPER-12': 'ZOOKEEPER-12:QuorumPeer.loadDataBase:1193:acceptedEpoch<currentEpoch',
}
SEEDS = ('healthy-a', 'healthy-b')


def rows(path):
    result = []
    for line in Path(path).read_text().splitlines():
        cells = line.split('\t')
        if len(cells) < 4:
            raise ValueError('short event: ' + line)
        result.append((int(cells[0]), cells[1], cells[2:-1]))
    return result


def selector(fields):
    return '@@'.join(fields[:4])


def io_events(trace):
    return [(seq, fields) for seq, kind, fields in trace if kind == 'IO']


def guard_events(trace, check, after=0, peer=None):
    return [(seq, fields) for seq, kind, fields in trace
            if kind == 'TARGET_GUARD' and seq > after and len(fields) >= 6
            and fields[0] == check and fields[2] == 'firstServer'
            and (peer is None or fields[3] == peer)
            and fields[1] == 'peer:' + fields[3]]


def audit_seed(run_id):
    directory = ROOT / run_id
    if not (directory / 'run.json').is_file():
        return {'run_id': run_id, 'status': 'pending'}
    receipt = json.loads((directory / 'run.json').read_text())
    errors = []
    if receipt['exit_code'] != 0 or receipt['plan'] != []:
        errors.append('original healthy JUnit failed or had a plan')
    if not (directory / 'events.tsv').is_file() or not (directory / 'coverage.tsv').is_file():
        return {'run_id': run_id, 'status': 'fail', 'errors': ['trace or coverage missing']}
    trace = rows(directory / 'events.tsv')
    selected = [f for _, k, f in trace if k == 'FIRST_SERVER_BIND']
    if len(selected) != 1:
        errors.append('need exactly one firstServer SID/snapDir binding')
    first = selected[0] if len(selected) == 1 else ['', '']
    sid, selected_dir = first[:2]
    peers = {}
    for _, kind, fields in trace:
        if kind != 'PEER_BIND' or len(fields) < 3:
            continue
        old = peers.setdefault(fields[0], fields[1])
        if old != fields[1]:
            errors.append('peer SID rebound to another snapshot directory')
    if set(peers) != {'0', '1', '2'} or peers.get(sid) != selected_dir or sid != '0':
        errors.append('firstServer must join exactly three registered peers and source slot 0')
    if any(kind in ('FAULT_APPLIED', 'FAULT_MATCHED', 'TARGET_THROW') for _, kind, _ in trace):
        errors.append('healthy trace contains fault or selected target exception')
    io = io_events(trace)
    families = set()
    stable_selectors = set()
    for seq, fields in io:
        if len(fields) < 7:
            errors.append('short bound I/O')
            continue
        site, actor, resource, ordinal, local = fields[:5]
        if local not in peers or actor != 'peer:' + local or not resource.startswith('file:'):
            errors.append('I/O actor differs from actual peer/file owner')
            continue
        filename = resource.split(':', 2)[1]
        previous = next(((k, f) for s, k, f in reversed(trace) if s == seq - 1), None)
        if previous is None or previous[0] not in ('FILE_RAW', 'ATOMIC_FILE_RAW', 'TEST_FILE_RAW'):
            errors.append('bound I/O has no adjacent raw File receiver evidence')
            continue
        kind, raw = previous
        if kind == 'FILE_RAW':
            raw_file = raw[2]
            if raw[1] != local or raw[3] != actor:
                errors.append('peer receiver and raw file disagree')
        elif kind == 'ATOMIC_FILE_RAW':
            raw_file = raw[1]
            if raw[3] != actor or raw[2] != raw_file + '.tmp':
                errors.append('atomic origFile/tmpFile pair or owner disagrees')
        else:
            raw_file = raw[0]
            if raw[1] != local or raw[2] != actor:
                errors.append('test file and firstServer owner disagree')
        if str(Path(raw_file).resolve().parent) != str(Path(peers[local]).resolve()) or \
                Path(raw_file).name != filename:
            errors.append('raw file path differs from selected actor/resource')
        families.add('@@'.join(fields[:3]))
        stable_selectors.add(selector(fields))
    counts = {}
    for case, check in CHECKS.items():
        guards = guard_events(trace, check, peer=sid)
        counts[case] = len(guards)
        if not guards:
            errors.append(case + ' selected peer0 guard missing')
        elif case == 'ZOOKEEPER-11' and not any('tmpExists=true' in f[5] for _, f in guards):
            errors.append('currentEpoch.tmp healthy guard did not observe existing temp file')
        elif case == 'ZOOKEEPER-12' and not any('less=false' in f[5] for _, f in guards):
            errors.append('accepted/current healthy ordering not observed')
    if not families or not (directory / 'coverage.tsv').read_text().strip():
        errors.append('no bound epoch I/O or production line coverage')
    return {'run_id': run_id, 'status': 'pass' if not errors else 'fail',
            'errors': errors, 'first_server_sid': sid, 'peer_snapdirs': peers,
            'guard_counts': counts, 'bound_io_count': len(io),
            'stable_families': sorted(families), 'stable_selectors': sorted(stable_selectors),
            'trace_sha256': sha(directory / 'events.tsv'),
            'coverage_sha256': sha(directory / 'coverage.tsv'),
            'receipt': receipt}


def locked_hashes():
    names = ('build_adapter.py', 'run_v2.py', 'calibrate_v2.py', 'campaign_v2.py')
    return {name: sha(CASE / name) for name in names}


def calibrate():
    build = verify_build()
    seeds = [audit_seed(run_id) for run_id in SEEDS]
    if any(seed['status'] != 'pass' for seed in seeds):
        raise RuntimeError('two original actor-aware healthy calibrations must pass')
    common = set(seeds[0]['stable_selectors']) & set(seeds[1]['stable_selectors'])
    first = seeds[0]['first_server_sid']
    if first != seeds[1]['first_server_sid'] or not common:
        raise RuntimeError('firstServer SID or exact bound I/O selectors unstable')
    for field in ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
                  'classpath_sha256', 'original_source_commit'):
        if seeds[0]['receipt'][field] != seeds[1]['receipt'][field]:
            raise RuntimeError('healthy receipts differ on ' + field)
    if seeds[0]['receipt']['agent_sha256'] != build['agent_sha256']:
        raise RuntimeError('agent differs from offline build')
    result = {'case_ids': list(CHECKS), 'first_server_sid': first,
              'agent_sha256': sha(AGENT), 'runner_sha256': sha(RUNNER),
              'script_hashes': locked_hashes(), 'common_selectors': sorted(common),
              'healthy': seeds}
    temp = CASE / 'calibration-receipt.json.tmp'
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    temp.replace(CASE / 'calibration-receipt.json')
    print(json.dumps({'status': 'pass', 'first_server_sid': first,
                      'common_selectors': len(common),
                      'guards': [seed['guard_counts'] for seed in seeds]}, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--worker-id', type=int)
    parser.add_argument('--worker-count', type=int, default=16)
    args = parser.parse_args()
    verify_build()
    if not args.run:
        print(json.dumps({'status': 'prepared_only', 'junit_executed': False,
                          'seeds': list(SEEDS), 'needs_worker_slot': True}, sort_keys=True))
        return
    if args.worker_id is None:
        parser.error('--run requires assigned --worker-id')
    for run_id in SEEDS:
        if not (ROOT / run_id / 'run.json').is_file():
            run(run_id, [], args.worker_id, args.worker_count)
    calibrate()


if __name__ == '__main__':
    main()
