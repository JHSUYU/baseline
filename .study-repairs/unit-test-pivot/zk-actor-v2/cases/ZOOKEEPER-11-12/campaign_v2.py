#!/usr/bin/env python3
"""Resumable actor/file-aware epoch fault campaign with separate ZK11/12 counters."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import shutil

from build_adapter import sha
from calibrate_v2 import (CASE, CHECKS, ROOT, SEEDS, calibrate, guard_events,
                          io_events, locked_hashes, rows, selector)
from run_v2 import AGENT, run, verify_build

STATE = ROOT / 'zk1112-v2-state.json'
LOCK = ROOT / 'zk1112-v2.lock'
MAX_SELECTED = 480


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def plan_id(plan):
    return json.dumps(plan, separators=(',', ':'))


def io_family(fields):
    return '@@'.join(fields[:3])


def selected_target(trace, case, peer, after=0):
    return guard_events(trace, CHECKS[case], after, peer)


def candidates(trace, case, peer, after=0):
    guards = selected_target(trace, case, peer, after)
    if not guards:
        return []
    cutoff = guards[0][0]
    seen = set()
    result = []
    for seq, fields in io_events(trace):
        if not (after < seq < cutoff) or len(fields) < 7:
            continue
        site, actor, resource, ordinal, local = fields[:5]
        if actor != 'peer:' + local or local not in ('0', '1', '2') or \
                not resource.startswith('file:') or \
                site.startswith('CurrentEpochWriteFailureTest#test:'):
            continue
        key = selector(fields)
        if key not in seen:
            seen.add(key)
            result.append({'selector': key, 'family': io_family(fields),
                           'actor': actor, 'resource': resource, 'seq': seq})
    return result


def initialize():
    build = verify_build()
    calibrated = calibrate()
    trace_a = rows(ROOT / SEEDS[0] / 'events.tsv')
    trace_b = rows(ROOT / SEEDS[1] / 'events.tsv')
    peer = calibrated['first_server_sid']
    queue = []
    all_families = set()
    for case in CHECKS:
        other = {item['selector'] for item in candidates(trace_b, case, peer)}
        points = [item for item in candidates(trace_a, case, peer)
                  if item['selector'] in other]
        if not points:
            raise RuntimeError(case + ' has no exact actor/file I/O before peer0 guard in both seeds')
        all_families.update(item['family'] for item in points)
        groups = {}
        for item in points:
            groups.setdefault(item['family'], []).append(item)
        ordered = []
        while any(groups.values()):
            for family in sorted(groups):
                if groups[family]:
                    ordered.append(groups[family].pop(0))
        queue.extend({'case': case, 'plan': [item['selector']],
                      'gain': 0, 'wait': 0} for item in ordered)
    coverage = set()
    for seed in SEEDS:
        coverage.update((ROOT / seed / 'coverage.tsv').read_text().splitlines())
    state = {
        'schema': 1, 'case_ids': list(CHECKS), 'status': 'running',
        'agent_sha256': build['agent_sha256'],
        'calibration_sha256': sha(CASE / 'calibration-receipt.json'),
        'script_hashes': locked_hashes(), 'first_server_sid': peer,
        'budgets': {case: {'effective_target': 80, 'max_faults': 8,
                           'effective_count': 0, 'extension_decided': False}
                    for case in CHECKS},
        'max_selected': MAX_SELECTED, 'selected_count': 0,
        'queue': queue, 'seen': [], 'results': [], 'inflight': None,
        'seen_coverage': sorted(coverage), 'seen_families': sorted(all_families),
    }
    atomic(STATE, state)
    return state


def verify_state(state):
    if state['agent_sha256'] != sha(AGENT) or \
            state['calibration_sha256'] != sha(CASE / 'calibration-receipt.json') or \
            state['script_hashes'] != locked_hashes():
        raise RuntimeError('agent, healthy calibration, or controller changed mid-campaign')


def choose(state):
    rng = random.Random(1112000 + state['selected_count'])
    for job in state['queue']:
        job['wait'] += 1
    ranked = []
    for job in state['queue']:
        budget = state['budgets'][job['case']]
        if budget['effective_count'] >= budget['effective_target'] or \
                len(job['plan']) > budget['max_faults']:
            ranked.append(float('-inf'))
            continue
        deficit = budget['effective_target'] - budget['effective_count']
        ranked.append(4 * job['gain'] + min(job['wait'], 40) / 10
                      + min(len(job['plan']), 6) * 2 + deficit / 20
                      + rng.random() / 8)
    if not ranked or max(ranked) == float('-inf'):
        return None
    return state['queue'].pop(max(range(len(ranked)), key=ranked.__getitem__))


def audit_actors(trace):
    peers = {}
    for _, kind, fields in trace:
        if kind == 'PEER_BIND':
            sid, path = fields[:2]
            if sid in peers and peers[sid] != path:
                raise RuntimeError('fault run rebound peer SID to another snapshot directory')
            peers[sid] = path
    for seq, fields in io_events(trace):
        if len(fields) < 7:
            raise RuntimeError('short bound I/O')
        actor, resource, local = fields[1], fields[2], fields[4]
        if local not in peers or actor != 'peer:' + local or not resource.startswith('file:'):
            raise RuntimeError('bound I/O actor differs from QuorumPeer file owner')
        previous = next(((k, f) for s, k, f in reversed(trace) if s == seq - 1), None)
        if previous is None or previous[0] not in ('FILE_RAW', 'ATOMIC_FILE_RAW', 'TEST_FILE_RAW'):
            raise RuntimeError('I/O lacks adjacent raw File receiver')
        kind, raw = previous
        path = raw[2] if kind == 'FILE_RAW' else raw[1] if kind == 'ATOMIC_FILE_RAW' else raw[0]
        raw_owner = raw[3] if kind != 'TEST_FILE_RAW' else raw[2]
        if raw_owner != actor or Path(path).resolve().parent != Path(peers[local]).resolve() or \
                Path(path).name != resource.split(':', 2)[1]:
            raise RuntimeError('raw File owner/name disagrees with bound I/O selector')
        if kind == 'FILE_RAW' and raw[1] != local:
            raise RuntimeError('peer receiver differs from file owner')
        if kind == 'ATOMIC_FILE_RAW' and raw[2] != path + '.tmp':
            raise RuntimeError('atomic origFile/tmpFile pair changed')
    return {'bound_peers': sorted(peers), 'bound_io': len(io_events(trace))}


def strict_plan(trace, plan):
    matched = [(s, f) for s, k, f in trace if k == 'FAULT_MATCHED']
    applied = [(s, f) for s, k, f in trace if k == 'FAULT_APPLIED']
    if [selector(f) for _, f in matched] != plan or \
            [selector(f) for _, f in applied] != plan:
        return False, 'ordered fault plan did not fully apply'
    for (ms, mf), (as_, af) in zip(matched, applied):
        if as_ != ms + 1 or selector(mf) != selector(af) or \
                not any(k == 'IO' and s == ms - 1 and selector(f) == selector(mf)
                        for s, k, f in trace):
            return False, 'fault lacked preceding exact observed I/O'
    return True, ''


def analyze(state, job, run_id, receipt):
    directory = ROOT / run_id
    trace = rows(directory / 'events.tsv') if (directory / 'events.tsv').is_file() else []
    actor_audit = audit_actors(trace)
    strict, reason = strict_plan(trace, job['plan'])
    applied = [s for s, k, _ in trace if k == 'FAULT_APPLIED']
    last = max(applied, default=0)
    peer = state['first_server_sid']
    case_results = {}
    for case, check in CHECKS.items():
        guards = selected_target(trace, case, peer, last) if strict else []
        throws = [(s, f) for s, k, f in trace if k == 'TARGET_THROW' and s > last
                  and len(f) >= 5 and f[0] == check and f[1] == 'peer:' + peer
                  and f[2] == 'firstServer' and f[3] == peer]
        case_results[case] = {
            'effective': strict and bool(guards), 'postfault_guards': len(guards),
            'target_throws': len(throws) if strict else 0,
            'bug_mark': 'candidate_needs_source_review' if strict and guards and throws else 'none',
        }
    effective_any = any(r['effective'] for r in case_results.values())
    current_coverage = set((directory / 'coverage.tsv').read_text().splitlines()) \
        if effective_any and (directory / 'coverage.tsv').is_file() else set()
    before = set(state['seen_coverage'])
    after_points = candidates(trace, job['case'], peer, last) if case_results[job['case']]['effective'] else []
    families = {x['family'] for x in after_points}
    new_families = families - set(state['seen_families'])
    result = {
        'run_id': run_id, 'target_case': job['case'], 'plan': job['plan'],
        'elapsed_seconds': receipt['elapsed_seconds'], 'junit_exit': receipt['exit_code'],
        'strict_injection': strict, 'applied_faults': len(applied),
        'invalid_reason': reason, 'actor_audit': actor_audit,
        'case_results': case_results, 'new_coverage_lines': len(current_coverage - before),
        'new_io_families': len(new_families),
        'evidence': str(directory),
    }
    return result, current_coverage, families, after_points


def enqueue(state, case, plan, gain):
    budget = state['budgets'][case]
    key = case + ':' + plan_id(plan)
    if len(plan) > budget['max_faults'] or key in state['seen'] or \
            any(x['case'] == case and x['plan'] == plan for x in state['queue']):
        return
    state['queue'].append({'case': case, 'plan': plan, 'gain': gain, 'wait': 0})


def decide_extensions(state):
    for case, budget in state['budgets'].items():
        if budget['extension_decided'] or budget['effective_count'] < 80:
            continue
        recent = [x for x in state['results'] if x['case_results'][case]['effective']][-8:]
        budget['extension_decided'] = True
        if len(recent) == 8 and any(x['new_coverage_lines'] or x['new_io_families']
                                    for x in recent):
            budget['effective_target'] = 128
            budget['max_faults'] = 10
            budget['extension_reason'] = 'late code or actor-bound epoch I/O novelty'


def record(state, job, run_id, receipt):
    if receipt['plan'] != job['plan'] or receipt['agent_sha256'] != state['agent_sha256']:
        raise RuntimeError('trial receipt differs from scheduled plan/agent')
    result, coverage, families, points = analyze(state, job, run_id, receipt)
    for case, case_result in result['case_results'].items():
        if case_result['effective']:
            state['budgets'][case]['effective_count'] += 1
    if any(x['effective'] for x in result['case_results'].values()):
        state['seen_coverage'] = sorted(set(state['seen_coverage']) | coverage)
        state['seen_families'] = sorted(set(state['seen_families']) | families)
    if result['case_results'][job['case']]['effective'] and \
            len(job['plan']) < state['budgets'][job['case']]['max_faults']:
        chosen = []
        seen_families = set()
        for point in points:
            if point['family'] not in seen_families:
                chosen.append(point)
                seen_families.add(point['family'])
        for point in points[-8:] + points[:4]:
            if point not in chosen:
                chosen.append(point)
        gain = result['new_coverage_lines'] + result['new_io_families']
        for point in chosen[:24]:
            enqueue(state, job['case'], job['plan'] + [point['selector']], gain)
    state['seen'].append(job['case'] + ':' + plan_id(job['plan']))
    state['results'].append(result)
    state['inflight'] = None
    decide_extensions(state)
    atomic(ROOT / run_id / 'trial.json', result)
    atomic(STATE, state)
    counts = {case: item['effective_count'] for case, item in state['budgets'].items()}
    throws = {case: item['target_throws'] for case, item in result['case_results'].items()}
    print(f'ZK1112 V2 {run_id} exact={result["strict_injection"]} '
          f'counts={counts} throws={throws} '
          f'coverage+={result["new_coverage_lines"]} io+={result["new_io_families"]}',
          flush=True)


def recover(state):
    job = state['inflight']
    if job is None:
        return
    run_id = job['run_id']
    completed = ROOT / run_id / 'run.json'
    if completed.is_file():
        record(state, job, run_id, json.loads(completed.read_text()))
        return
    partial = ROOT / run_id
    if partial.exists():
        archive = ROOT / 'interrupted' / run_id
        archive.parent.mkdir(exist_ok=True)
        if archive.exists():
            raise RuntimeError('interrupted evidence archive already exists')
        shutil.move(str(partial), str(archive))
    state['queue'].insert(0, {k: v for k, v in job.items() if k != 'run_id'})
    state['inflight'] = None
    atomic(STATE, state)


def finished(state):
    return all(item['effective_count'] >= item['effective_target']
               for item in state['budgets'].values())


def campaign(slot, slots):
    ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.is_file() else initialize()
        verify_state(state)
        recover(state)
        while not finished(state) and state['selected_count'] < state['max_selected']:
            job = choose(state)
            if job is None:
                break
            state['selected_count'] += 1
            run_id = f'trial-{state["selected_count"]:03d}'
            state['inflight'] = {**job, 'run_id': run_id}
            atomic(STATE, state)
            receipt = run(run_id, job['plan'], slot, slots)
            record(state, job, run_id, receipt)
        state['status'] = 'complete' if finished(state) else 'selected_cap' \
            if state['selected_count'] >= state['max_selected'] else 'queue_exhausted'
        atomic(STATE, state)
        print(json.dumps({'status': state['status'], 'selected': state['selected_count'],
                          'budgets': state['budgets']}, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--worker-id', type=int)
    parser.add_argument('--worker-count', type=int, default=16)
    args = parser.parse_args()
    verify_build()
    if not args.run:
        print(json.dumps({'status': 'prepared_only', 'junit_executed': False,
                          'case_ids': list(CHECKS), 'budgets': '80 effective/max8 each; '
                          'conditional 128/max10'}, sort_keys=True))
        return
    if args.worker_id is None:
        parser.error('--run requires assigned --worker-id')
    campaign(args.worker_id, args.worker_count)


if __name__ == '__main__':
    main()
