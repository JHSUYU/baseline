#!/usr/bin/env python3
"""Resume a target-retaining, actor-aware CrashFuzz-style ZK03 campaign.

The denominator is effective trials: the complete ordered fault plan must be
applied to bound actors of the original moved session and its leader check,
and the same logical target guard must execute after the final fault.
"""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys
import time

from audit_calibration import CHECK, one as audit_seed
from calibrate_healthy import AGENT, MIN_FREE_BYTES, ROOT, sha
from run_trial import run

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from receipt_validator import ReceiptError, parse_events, validate_rows

HERE = Path(__file__).resolve().parent
CHECKPOINT = ROOT / 'v2-campaign.json'
LEDGER = ROOT / 'v2-trials.jsonl'
LOCK = ROOT / 'v2-campaign.lock'
INITIAL_BUDGET = 80
EXTENDED_BUDGET = 128
INITIAL_MAX_FAULTS = 8
EXTENDED_MAX_FAULTS = 10
MAX_ATTEMPTS = 480
TARGET = {'check': CHECK, 'actor': '*', 'role': 'leader',
          'peer': '*', 'session_tag': 'movedSession'}


def atomic_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    os.replace(tmp, path)


def selector(fields):
    return '@@'.join(fields[:4])


def feedback_family(fields):
    resource = fields[2]
    resource = re.sub(r'(?<=:channel:)\d+(?=:)', '*', resource)
    resource = re.sub(r'^connection:\d+(?=:)', 'connection:*', resource)
    return '@@'.join((fields[0], fields[1], resource))


def complete_io_site(site):
    return (site.startswith('org.apache.zookeeper.ClientCnxnSocketNIO#doIO:119:')
            or (site.startswith('org.apache.zookeeper.server.NIOServerCnxn#handleWrite:')
                and site.endswith(':packetSent()V')))


def io_relation(fields):
    if len(fields) < 7:
        return None
    if fields[6] == 'movedSession' and (
            fields[1].startswith('client:handle:') or
            fields[1].startswith('peer:')):
        return 'same_session'
    if fields[1].startswith('peer:') and fields[4]:
        return 'same_peer'
    return None


def target_guards(rows, after=0):
    return [(seq, fields) for seq, kind, fields in rows
            if kind == 'TARGET_GUARD' and seq > after and len(fields) >= 6
            and fields[0] == CHECK and fields[1].startswith('peer:')
            and fields[2] == 'leader' and fields[4] == 'movedSession']


def candidates(rows, after=0):
    guards = target_guards(rows, after)
    if not guards:
        return []
    # The original workload moves one raw session across eleven handles;
    # target checks recur throughout that sequence, so retain later I/O too.
    end = guards[-1][0]
    seen = set()
    result = []
    for seq, kind, fields in rows:
        if kind != 'IO' or seq <= after or seq >= end or \
                not complete_io_site(fields[0]):
            continue
        relation = io_relation(fields)
        if relation is None:
            continue
        key = selector(fields)
        if key not in seen:
            result.append({'selector': key, 'relation': relation,
                           'family': feedback_family(fields), 'sequence': seq})
            seen.add(key)
    return result


def seed_queue():
    runs = [audit_seed('healthy-a'), audit_seed('healthy-b')]
    if any(x['status'] != 'pass' for x in runs):
        raise RuntimeError('two original JUnit actor calibrations must both pass')
    common = set(runs[0]['client_families']) & set(runs[1]['client_families'])
    if len(common) < 2:
        raise RuntimeError('no stable moved-session client family')
    metadata = [json.loads((ROOT / x / 'run.json').read_text())
                for x in ('healthy-a', 'healthy-b')]
    if any(x['agent_sha256'] != sha(AGENT) for x in metadata):
        raise RuntimeError('agent changed since healthy seeds')
    rows = parse_events(ROOT / 'healthy-a/events.tsv')
    initial = candidates(rows)
    if not initial:
        raise RuntimeError('healthy seed has no bound target-related preguard I/O')
    # Family rotation tests distinct moved handles, operation kinds and peers
    # before repeated ordinals, preserving actual runtime selectors.
    groups = {}
    for item in initial:
        groups.setdefault(item['family'], []).append(item)
    ordered = []
    while any(groups.values()):
        for family in sorted(groups):
            if groups[family]:
                ordered.append(groups[family].pop(0))
    jobs = [{'plan': [x['selector']], 'relations': [x['relation']],
             'parent': 'healthy-a', 'score': 10.0} for x in ordered]
    baseline_cov = set().union(*(
        set((ROOT / name / 'coverage.tsv').read_text().splitlines())
        for name in ('healthy-a', 'healthy-b')))
    state = {'schema': 3, 'feedback_baseline': 'healthy_union_v2',
             'status': 'running', 'budget_effective': INITIAL_BUDGET,
             'max_faults': INITIAL_MAX_FAULTS, 'max_attempts': MAX_ATTEMPTS,
             'next_trial': 1, 'pending': jobs, 'queued': [x['plan'] for x in jobs],
             'inflight': [], 'results': [], 'effective_count': 0,
             'seen_coverage': sorted(baseline_cov),
             'seen_families': sorted({x['family'] for name in ('healthy-a', 'healthy-b')
                                      for x in candidates(parse_events(ROOT / name / 'events.tsv'))}),
             'healthy_elapsed_seconds': sum(x['elapsed_seconds'] for x in metadata),
             'created_at': time.time(), 'extended': False,
             'calibration': runs}
    atomic_json(CHECKPOINT, state)
    return state


def save(state):
    atomic_json(CHECKPOINT, state)


def enqueue(state, plan, relations, parent, score):
    if len(plan) > state['max_faults'] or plan in state['queued']:
        return False
    state['queued'].append(plan)
    state['pending'].append({'plan': plan, 'relations': relations,
                             'parent': parent, 'score': score})
    return True


def choose(state):
    # Favor new coverage/I/O and recovery depth, with a small aging/random
    # term so deeper sequences do not monopolize the queue.
    rng = random.Random(state['next_trial'] * 76543)
    ranked = [(job['score'] + min(len(job['plan']), 6) * 0.5 +
               rng.random() * 2.0 + (len(state['pending']) - index) * 0.003,
               index) for index, job in enumerate(state['pending'])]
    _, index = max(ranked)
    return state['pending'].pop(index)


def owner_receipt(rows, target_sequence):
    target = next((fields for seq, kind, fields in rows
                   if seq == target_sequence and kind == 'TARGET_GUARD'), None)
    if target is None or len(target) < 7:
        return None
    leaders = [fields[0] for _, kind, fields in rows
               if kind == 'LEADER_BIND' and len(fields) >= 1]
    if len(leaders) != 1 or target[1] != 'peer:' + leaders[0] or target[3] != leaders[0]:
        return None
    raw_sessions = {fields[0] for _, kind, fields in rows
                    if kind == 'SESSION_BIND' and len(fields) >= 3
                    and fields[2] == 'movedSession'}
    if len(raw_sessions) != 1:
        return None
    matches = [(seq, fields) for seq, kind, fields in rows
               if kind == 'OWNER_BIND' and seq < target_sequence
               and len(fields) >= 5 and fields[-1] == target[-1]]
    if not matches:
        return None
    _, fields = matches[-1]
    if fields[0] != target[3] or fields[1] not in raw_sessions:
        return None
    if fields[3] != target[5] or not fields[2].startswith(('local:', 'forwarder:')):
        return None
    return {'peer': fields[0], 'raw_session': fields[1],
            'requested_owner': fields[2], 'session_state': fields[3]}


def evaluate(job, receipt):
    dest = ROOT / job['run_id']
    event_file = dest / 'events.tsv'
    rows = parse_events(event_file) if event_file.is_file() else []
    contract = {'plan': job['plan'], 'fault_relations': job['relations'],
                'target': TARGET}
    reason = None
    try:
        strict_receipt = validate_rows(rows, contract)
    except (ReceiptError, ValueError, IndexError) as error:
        reason = str(error)
        strict_receipt = None
    owner = owner_receipt(rows, strict_receipt['target_sequence']) if strict_receipt else None
    if strict_receipt and owner is None:
        strict_receipt = None
        reason = 'postfault selected guard lacks raw-session owner/state receipt'
    effective = strict_receipt is not None
    last_fault = max((seq for seq, kind, _ in rows if kind == 'FAULT_APPLIED'), default=0)
    # Only a throw on the proven postfault target actor/session can be a
    # candidate. Raw throws from lost-target or another leader are retained
    # in events.tsv but cannot affect this check's verdict or fuzz feedback.
    selected_target = (strict_receipt['target_actor'] if effective else None)
    selected_peer = owner['peer'] if owner else None
    throws = [fields for seq, kind, fields in rows
              if effective and kind == 'TARGET_THROW' and seq > last_fault
              and len(fields) >= 6 and fields[0] == CHECK
              and fields[1] == selected_target and fields[2] == 'leader'
              and fields[3] == selected_peer and fields[4] == 'movedSession']
    cov_file = dest / 'coverage.tsv'
    coverage = set(cov_file.read_text().splitlines()) if cov_file.is_file() else set()
    observed = candidates(rows, last_fault) if effective else []
    return {'run_id': job['run_id'], 'parent': job['parent'],
            'worker_slot': job['worker_slot'], 'plan': job['plan'],
            'relations': job['relations'], 'fault_count': len(job['plan']),
            'elapsed_seconds': receipt['elapsed_seconds'],
            'junit_exit': receipt['exit_code'], 'effective': effective,
            'strict_receipt': strict_receipt, 'invalid_reason': reason,
            'selected_owner_receipt': owner if effective else None,
            'selected_target_throw_count': len(throws),
            'selected_target_throws': throws,
            'needs_source_review': bool(throws),
            'coverage': sorted(coverage),
            'mutation_io': observed,
            'bug_mark': 'candidate_needs_source_review' if throws else 'none'}


def record(state, job, receipt):
    if receipt['plan'] != job['plan'] or receipt['agent_sha256'] != sha(AGENT):
        raise RuntimeError('trial artifact identity/plan differs from scheduled job')
    item = evaluate(job, receipt)
    previous_cov = set(state['seen_coverage'])
    previous_families = set(state['seen_families'])
    if item['effective']:
        new_cov = set(item['coverage']) - previous_cov
        new_families = {x['family'] for x in item['mutation_io']} - previous_families
        item['new_coverage_lines'] = len(new_cov)
        item['new_io_families'] = len(new_families)
        state['seen_coverage'] = sorted(previous_cov | set(item['coverage']))
        state['seen_families'] = sorted(previous_families |
                                        {x['family'] for x in item['mutation_io']})
        state['effective_count'] += 1
        if len(job['plan']) < state['max_faults']:
            mutation = item['mutation_io']
            # New I/O, near-guard I/O, and representative actor families.
            selected = []
            distinct = set()
            for event in mutation:
                if event['family'] not in distinct:
                    selected.append(event)
                    distinct.add(event['family'])
            for event in mutation[-8:] + mutation[:4]:
                if event not in selected:
                    selected.append(event)
            score = (8.0 if new_cov else 2.0) + min(len(new_cov), 20) * 0.3 + \
                (5.0 if new_families else 0.0)
            for event in selected[:24]:
                enqueue(state, job['plan'] + [event['selector']],
                        job['relations'] + [event['relation']], job['run_id'], score)
    else:
        item['new_coverage_lines'] = 0
        item['new_io_families'] = 0
    item.pop('coverage')
    item.pop('mutation_io')
    state['results'].append(item)
    state['inflight'] = [x for x in state['inflight'] if x['run_id'] != job['run_id']]
    with LEDGER.open('a') as output:
        output.write(json.dumps(item, sort_keys=True) + '\n')
        output.flush()
        os.fsync(output.fileno())
    save(state)
    print('ZK03 V2 trial={} slot={} depth={} exit={} effective={}/{} '
          'target_throw={} coverage+={} io+={} elapsed={:.3f}s {}'.format(
              job['run_id'], job['worker_slot'], len(job['plan']), item['junit_exit'],
              state['effective_count'], state['budget_effective'],
              item['selected_target_throw_count'], item['new_coverage_lines'],
              item['new_io_families'], item['elapsed_seconds'],
              item['invalid_reason'] or ''), flush=True)


def recover(state):
    inflight = state['inflight'][:]
    state['inflight'] = []
    for job in inflight:
        path = ROOT / job['run_id'] / 'run.json'
        if path.is_file():
            record(state, job, json.loads(path.read_text()))
            continue
        abandoned = ROOT / job['run_id']
        if abandoned.exists():
            retained = ROOT / 'failed-seeds' / (job['run_id'] + '-interrupted')
            retained.parent.mkdir(exist_ok=True)
            if retained.exists():
                raise RuntimeError('interrupted evidence archive already exists')
            shutil.move(str(abandoned), str(retained))
        state['pending'].insert(0, {key: value for key, value in job.items()
                                    if key not in ('run_id', 'worker_slot')})
    save(state)


def should_extend(state):
    tail = [x for x in state['results'] if x['effective']][-8:]
    return len(tail) == 8 and any(x['new_coverage_lines'] or x['new_io_families']
                                  for x in tail)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='start original JUnit cluster trials')
    parser.add_argument('--slots', default='15,16', help='reserved worker slots, comma separated')
    parser.add_argument('--worker-count', type=int, default=16)
    parser.add_argument('--max-new-trials', type=int,
                        help='pause after this many newly selected trials')
    args = parser.parse_args()
    if args.max_new_trials is not None and args.max_new_trials < 1:
        parser.error('--max-new-trials must be positive')
    try:
        slots = tuple(int(item) for item in args.slots.split(','))
    except ValueError:
        parser.error('--slots must be comma separated integers')
    if not slots or len(set(slots)) != len(slots) or any(
            slot < 1 or slot > args.worker_count for slot in slots):
        parser.error('--slots must be distinct and within --worker-count')
    if not args.run:
        print(json.dumps({'status': 'prepared_only', 'junit_executed': False,
                          'slots': slots, 'worker_count': args.worker_count,
                          'budget': '80 effective/max8; conditional 128/max10'}))
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else seed_queue()
        if state.get('feedback_baseline') != 'healthy_union_v2':
            raise RuntimeError('after-response checkpoint lacks two-healthy feedback baseline')
        if state['status'] not in ('running', 'paused_at_trial_boundary'):
            print(json.dumps({'status': state['status'],
                              'effective_count': state['effective_count']}))
            return
        state['status'] = 'running'
        recover(state)
        first_trial = state['next_trial']
        with ThreadPoolExecutor(max_workers=len(slots)) as executor:
            running = {}
            pause_reason = None
            while True:
                if shutil.disk_usage(ROOT.parent).free < MIN_FREE_BYTES:
                    pause_reason = 'paused_disk_under_2gib'
                if args.max_new_trials is not None and \
                        state['next_trial'] - first_trial >= args.max_new_trials:
                    pause_reason = 'paused_at_trial_boundary'
                if state['effective_count'] >= state['budget_effective'] and not running:
                    if not state['extended'] and should_extend(state):
                        state['extended'] = True
                        state['budget_effective'] = EXTENDED_BUDGET
                        state['max_faults'] = EXTENDED_MAX_FAULTS
                        print('ZK03 V2 late novelty: extend to 128 effective/max10', flush=True)
                    else:
                        state['status'] = 'budget_complete'
                        save(state)
                        break
                busy = {job['worker_slot'] for job in running.values()}
                for slot in slots:
                    if pause_reason or state['effective_count'] + len(running) >= state['budget_effective']:
                        break
                    if args.max_new_trials is not None and \
                            state['next_trial'] - first_trial >= args.max_new_trials:
                        break
                    if len(state['results']) + len(running) >= MAX_ATTEMPTS:
                        break
                    if slot in busy or not state['pending']:
                        continue
                    job = choose(state)
                    job['run_id'] = 'trial-{:04d}'.format(state['next_trial'])
                    job['worker_slot'] = slot
                    state['next_trial'] += 1
                    state['inflight'].append(job)
                    save(state)
                    future = executor.submit(run, job['run_id'], job['plan'], slot,
                                             args.worker_count)
                    running[future] = job
                if not running:
                    state['status'] = (pause_reason or
                                       ('attempt_cap' if len(state['results']) >= MAX_ATTEMPTS
                                        else 'queue_exhausted'))
                    save(state)
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    job = running.pop(future)
                    receipt = future.result()
                    record(state, job, receipt)
        print(json.dumps({'status': state['status'],
                          'effective_count': state['effective_count'],
                          'attempts': len(state['results']),
                          'budget_effective': state['budget_effective'],
                          'max_faults': state['max_faults']}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
