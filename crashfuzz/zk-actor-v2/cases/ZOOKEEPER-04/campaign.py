#!/usr/bin/env python3
"""Resumable graph-free I/O/coverage-guided ZK04 campaign with strict actor receipts.

Only fully applied ordered plans followed by the selected follower2 guard for
the original client's same raw session enter the 80-effective denominator.
The CLI can stop after five new attempts for a bounded coexistence pilot.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time

from audit_calibration import CHECK, RUNS, one as audit_seed
from calibrate_healthy import AGENT, MIN_FREE_BYTES, ROOT, sha
from run_trial import run

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from receipt_validator import ReceiptError, parse_events, validate_rows

CHECKPOINT = ROOT / 'v2-campaign.json'
LEDGER = ROOT / 'v2-trials.jsonl'
LOCK = ROOT / 'v2-campaign.lock'
INITIAL_BUDGET = 80
EXTENDED_BUDGET = 128
INITIAL_MAX_FAULTS = 8
EXTENDED_MAX_FAULTS = 10
MAX_ATTEMPTS = 480
TARGET = {'check': CHECK, 'actor': 'peer-role:follower2',
          'role': 'follower2', 'peer': '*', 'session_tag': 'revalidateSession'}


def save(state):
    temp = CHECKPOINT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    os.replace(temp, CHECKPOINT)
    # Checkpoint is authoritative; rebuilding avoids duplicate ledger rows
    # after a crash between the two durable writes.
    temp = LEDGER.with_suffix('.jsonl.tmp')
    with temp.open('w') as output:
        for item in state['results']:
            output.write(json.dumps(item, sort_keys=True) + '\n')
    os.replace(temp, LEDGER)


def selector(fields):
    return '@@'.join(fields[:4])


def relation(fields, follower2):
    if len(fields) < 7 or fields[6] != 'revalidateSession':
        return None
    if fields[1] == 'client:revalidate-client:session:revalidateSession':
        if fields[5] == follower2:
            return 'counterparty_to_peer'
        # Initial follower1 I/O is still from the original logical client.
        return 'same_session'
    if fields[1] == 'peer-role:follower2:session:revalidateSession' \
            and fields[4] == follower2:
        return 'same_peer'
    if fields[1] == 'peer-role:follower2' and fields[4] == follower2:
        return 'epoch_file_owner'
    return None


def selected_guards(rows, after=0):
    return [(seq, fields) for seq, kind, fields in rows
            if seq > after and kind == 'TARGET_GUARD' and len(fields) >= 6
            and fields[0] == CHECK and fields[1] == 'peer-role:follower2'
            and fields[2] == 'follower2' and fields[4] == 'revalidateSession']


def candidates(rows, after=0):
    guards = selected_guards(rows, after)
    if not guards:
        return []
    end = guards[-1][0]
    follower2 = guards[-1][1][3]
    seen = set()
    result = []
    for seq, kind, fields in rows:
        if kind != 'IO' or not after < seq < end:
            continue
        rel = relation(fields, follower2)
        key = selector(fields)
        if rel is None or key in seen:
            continue
        seen.add(key)
        result.append({'selector': key, 'relation': rel,
                       'family': '@@'.join(fields[:3]), 'sequence': seq})
    return result


def seed_queue():
    audited = [audit_seed(run_id) for run_id in RUNS]
    if any(item['status'] != 'pass' for item in audited):
        raise RuntimeError('two final original-cluster actor calibrations must pass')
    metadata = [json.loads((ROOT / name / 'run.json').read_text()) for name in RUNS]
    if any(item['agent_sha256'] != sha(AGENT) for item in metadata):
        raise RuntimeError('agent JAR changed after final healthy calibration')
    rows = parse_events(ROOT / (RUNS[0] + '/events.tsv'))
    initial = candidates(rows)
    if not initial:
        raise RuntimeError('healthy run has no actor-bound pretarget I/O')
    # Rotate actors/families before revisiting a site's next ordinal.
    groups = {}
    for item in initial:
        groups.setdefault(item['family'], []).append(item)
    ordered = []
    while any(groups.values()):
        for family in sorted(groups):
            if groups[family]:
                ordered.append(groups[family].pop(0))
    jobs = [{'plan': [item['selector']], 'relations': [item['relation']],
             'parent': RUNS[0], 'score': 10.0} for item in ordered]
    baseline_cov = set((ROOT / RUNS[0] / 'coverage.tsv').read_text().splitlines())
    state = {'schema': 1, 'case_id': 'ZOOKEEPER-04', 'status': 'running',
             'budget_effective': INITIAL_BUDGET, 'max_faults': INITIAL_MAX_FAULTS,
             'max_attempts': MAX_ATTEMPTS, 'next_trial': 1, 'pending': jobs,
             'queued': [job['plan'] for job in jobs], 'inflight': [],
             'results': [], 'effective_count': 0,
             'seen_coverage': sorted(baseline_cov),
             'seen_families': sorted({item['family'] for item in initial}),
             'healthy_elapsed_seconds': sum(item['elapsed_seconds'] for item in metadata),
             'created_at': time.time(), 'extended': False,
             'calibration_runs': list(RUNS)}
    save(state)
    return state


def enqueue(state, plan, relations, parent, score):
    if len(plan) > state['max_faults'] or plan in state['queued']:
        return False
    state['queued'].append(plan)
    state['pending'].append({'plan': plan, 'relations': relations,
                             'parent': parent, 'score': score})
    return True


def choose(state):
    rng = random.Random(state['next_trial'] * 34319)
    index = max(range(len(state['pending'])), key=lambda i:
                state['pending'][i]['score']
                + min(len(state['pending'][i]['plan']), 6) * 0.5
                + rng.random() * 2.0
                + (len(state['pending']) - i) * 0.003)
    return state['pending'].pop(index)


def target_owner_receipt(rows, target_sequence):
    target = next((fields for seq, kind, fields in rows
                   if seq == target_sequence and kind == 'TARGET_GUARD'), None)
    if target is None or len(target) < 7:
        return None
    roles = [fields for _, kind, fields in rows if kind == 'ROLE_BIND']
    sessions = [fields for _, kind, fields in rows if kind == 'SESSION_BIND']
    if len(roles) != 1 or len(sessions) != 1 or roles[0][1] != target[3]:
        return None
    raw = sessions[0][0]
    owner = next((fields for seq, kind, fields in reversed(rows)
                  if kind == 'TARGET_OWNER_BIND' and 0 < target_sequence - seq <= 12
                  and fields[-1] == target[-1]), None)
    if owner is None or len(owner) < 6 or owner[0] != target[3] \
            or owner[1] != raw or owner[3] != target[1]:
        return None
    local_port = owner[2]
    channels = [(seq, fields) for seq, kind, fields in rows
                if kind == 'CHANNEL_BIND' and seq < target_sequence
                and len(fields) >= 4 and fields[0] == local_port
                and fields[1] == target[3]]
    if not channels:
        return None
    return {'peer_sid': owner[0], 'raw_session_id': raw,
            'client_ephemeral_port': local_port, 'client_channel': channels[-1][1][3],
            'client_last_zxid': owner[4]}


def evaluate(job, receipt):
    dest = ROOT / job['run_id']
    events = dest / 'events.tsv'
    rows = parse_events(events) if events.is_file() else []
    reason = None
    try:
        strict = validate_rows(rows, {'plan': job['plan'],
                                      'fault_relations': job['relations'],
                                      'target': TARGET})
    except (ReceiptError, ValueError, IndexError) as failure:
        strict = None
        reason = str(failure)
    owner = target_owner_receipt(rows, strict['target_sequence']) if strict else None
    if strict and owner is None:
        strict = None
        reason = 'postfault selected guard lacks exact raw-session/channel/peer owner receipt'
    effective = strict is not None
    last_fault = max((seq for seq, kind, _ in rows if kind == 'FAULT_APPLIED'), default=0)
    throws = [fields for seq, kind, fields in rows
              if seq > last_fault and kind == 'TARGET_THROW' and len(fields) >= 6
              and fields[:5] == [CHECK, 'peer-role:follower2', 'follower2',
                                  owner['peer_sid'] if owner else '', 'revalidateSession']]
    coverage_path = dest / 'coverage.tsv'
    coverage = set(coverage_path.read_text().splitlines()) if coverage_path.is_file() else set()
    observed = candidates(rows, last_fault) if effective else []
    return {'run_id': job['run_id'], 'parent': job['parent'],
            'worker_slot': job['worker_slot'], 'plan': job['plan'],
            'relations': job['relations'], 'fault_count': len(job['plan']),
            'elapsed_seconds': receipt['elapsed_seconds'], 'junit_exit': receipt['exit_code'],
            'effective': effective, 'strict_receipt': strict,
            'invalid_reason': reason, 'selected_owner_receipt': owner,
            'selected_target_throw_count': len(throws),
            'needs_source_review': bool(throws),
            'bug_mark': 'candidate_needs_source_review' if throws else 'none',
            '_coverage': coverage, '_mutation_io': observed}


def record(state, job, receipt):
    if receipt['plan'] != job['plan'] or receipt['agent_sha256'] != sha(AGENT):
        raise RuntimeError('trial plan or agent differs from scheduled job')
    item = evaluate(job, receipt)
    previous_cov = set(state['seen_coverage'])
    previous_families = set(state['seen_families'])
    if item['effective']:
        new_cov = item['_coverage'] - previous_cov
        new_families = {x['family'] for x in item['_mutation_io']} - previous_families
        item['new_coverage_lines'] = len(new_cov)
        item['new_io_families'] = len(new_families)
        state['seen_coverage'] = sorted(previous_cov | item['_coverage'])
        state['seen_families'] = sorted(previous_families |
                                        {x['family'] for x in item['_mutation_io']})
        state['effective_count'] += 1
        if len(job['plan']) < state['max_faults']:
            distinct = {}
            for io in item['_mutation_io']:
                distinct.setdefault(io['family'], io)
            selected = list(distinct.values()) + item['_mutation_io'][-8:]
            score = (8.0 if new_cov else 2.0) + min(len(new_cov), 20) * 0.3 \
                + (5.0 if new_families else 0.0)
            for io in selected[:24]:
                enqueue(state, job['plan'] + [io['selector']],
                        job['relations'] + [io['relation']], job['run_id'], score)
    else:
        item['new_coverage_lines'] = 0
        item['new_io_families'] = 0
    del item['_coverage'], item['_mutation_io']
    state['results'].append(item)
    state['inflight'] = [x for x in state['inflight'] if x['run_id'] != job['run_id']]
    save(state)
    print('ZK04 trial={} depth={} exit={} effective={}/{} throw={} cov+={} io+={} {:.3f}s {}'.format(
        job['run_id'], len(job['plan']), item['junit_exit'],
        state['effective_count'], state['budget_effective'],
        item['selected_target_throw_count'], item['new_coverage_lines'],
        item['new_io_families'], item['elapsed_seconds'], item['invalid_reason'] or ''), flush=True)


def recover(state):
    jobs = state['inflight'][:]
    state['inflight'] = []
    for job in jobs:
        path = ROOT / job['run_id'] / 'run.json'
        if path.is_file():
            record(state, job, json.loads(path.read_text()))
            continue
        abandoned = ROOT / job['run_id']
        if abandoned.exists():
            retained = ROOT / 'interrupted' / job['run_id']
            retained.parent.mkdir(exist_ok=True)
            if retained.exists():
                raise RuntimeError('interrupted raw evidence already retained')
            shutil.move(str(abandoned), str(retained))
        state['pending'].insert(0, {key: value for key, value in job.items()
                                    if key not in ('run_id', 'worker_slot')})
    save(state)


def should_extend(state):
    tail = [x for x in state['results'] if x['effective']][-8:]
    return len(tail) == 8 and any(x['new_coverage_lines'] or x['new_io_families']
                                  or x['selected_target_throw_count'] for x in tail)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker-id', type=int, default=15)
    parser.add_argument('--worker-count', type=int, default=16)
    parser.add_argument('--max-new-attempts', type=int, default=0,
                        help='stop after this many new trials; 0 means full campaign')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else seed_queue()
        if args.prepare_only:
            print(json.dumps({'status': 'prepared', 'pending': len(state['pending']),
                              'effective_count': state['effective_count']}))
            return
        if state['status'] in ('paused_pilot', 'paused_disk_under_2gib'):
            state['status'] = 'running'
        if state['status'] != 'running':
            print(json.dumps({'status': state['status'],
                              'effective_count': state['effective_count']}))
            return
        recover(state)
        new_attempts = 0
        while state['status'] == 'running':
            if shutil.disk_usage(ROOT.parent).free < MIN_FREE_BYTES:
                state['status'] = 'paused_disk_under_2gib'
            elif state['effective_count'] >= state['budget_effective']:
                if not state['extended'] and should_extend(state):
                    state['extended'] = True
                    state['budget_effective'] = EXTENDED_BUDGET
                    state['max_faults'] = EXTENDED_MAX_FAULTS
                else:
                    state['status'] = 'budget_complete'
            elif len(state['results']) >= MAX_ATTEMPTS:
                state['status'] = 'attempt_cap'
            elif not state['pending']:
                state['status'] = 'queue_exhausted'
            elif args.max_new_attempts and new_attempts >= args.max_new_attempts:
                state['status'] = 'paused_pilot'
            if state['status'] != 'running':
                save(state)
                break
            job = choose(state)
            job['run_id'] = 'trial-{:04d}'.format(state['next_trial'])
            job['worker_slot'] = args.worker_id
            state['next_trial'] += 1
            state['inflight'].append(job)
            save(state)
            receipt = run(job['run_id'], job['plan'], args.worker_id,
                          args.worker_count, args.timeout)
            record(state, job, receipt)
            new_attempts += 1
        print(json.dumps({'status': state['status'],
                          'effective_count': state['effective_count'],
                          'attempts': len(state['results']),
                          'budget_effective': state['budget_effective'],
                          'max_faults': state['max_faults'],
                          'pending': len(state['pending'])}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
