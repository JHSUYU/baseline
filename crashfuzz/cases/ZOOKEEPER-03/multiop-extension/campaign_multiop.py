#!/usr/bin/env python3
"""Resumable independent fault stage for original QuorumTest MultiOp migration."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import time

import pilot_multiop as base

ROOT = base.ROOT
HERE = ROOT / 'campaign'
CHECKPOINT = HERE / 'checkpoint.json'
LEDGER = HERE / 'trials.jsonl'
LOCK = HERE / 'campaign.lock'
INITIAL_EFFECTIVE = 80
EXTENDED_EFFECTIVE = 128
INITIAL_MAX_FAULTS = 8
EXTENDED_MAX_FAULTS = 10
MAX_ATTEMPTS = 480


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    os.replace(temp, path)


def events(run_id):
    return base.parse_events(ROOT / run_id / 'events.tsv')


def future_io(run_id):
    rows = events(run_id)
    faults = [s for s, k, _, _ in rows if k == 'FAULT_APPLIED']
    if not faults:
        return []
    last = faults[-1]
    guard = next((s for s, k, f, _ in rows if s > last and k == 'TARGET_GUARD'
                  and len(f) >= 6 and f[0] == base.CHECK and f[2] == 'leader'
                  and f[4] == 'movedSession'), None)
    if guard is None:
        return []
    seen = set()
    out = []
    for s, kind, f, _ in rows:
        if kind != 'IO' or not last < s < guard or len(f) < 7 \
                or f[6] != 'movedSession' or 'session:movedSession' not in f[1]:
            continue
        selector = '@@'.join(f[:4])
        if selector not in seen:
            out.append({'selector': selector, 'family': '@@'.join(f[:3]), 'sequence': s})
            seen.add(selector)
    return out


def add(state, plan, parent, score):
    if len(plan) > state['max_faults'] or plan in state['seen_plans']:
        return False
    state['seen_plans'].append(plan)
    state['pending'].append({'plan': plan, 'parent': parent, 'score': score})
    return True


def initial_state():
    cal = base.calibrate()
    pilot_file = ROOT / 'pilot-checkpoint.json'
    pilot = json.loads(pilot_file.read_text())
    if pilot['status'] != 'pilot_complete' or pilot['next_index'] != len(pilot['queue']):
        raise RuntimeError('ten-trial pilot must finish before independent budget')
    if pilot['agent_sha256'] != base.sha(base.AGENT):
        raise RuntimeError('pilot agent differs')
    raw = {x['raw_session_id'] for x in cal['healthy']}
    if len(raw) != 2 or len({x['leader_sid'] for x in cal['healthy']}) != 1:
        raise RuntimeError('healthy original JUnit session/leader binding changed')
    stable = {x['selector'] for x in cal['healthy'][0]['io_candidates']} & \
             {x['selector'] for x in cal['healthy'][1]['io_candidates']}
    observed_families = {x['family'] for x in cal['healthy'][0]['io_candidates']}
    for item in pilot['results']:
        if item['effective']:
            observed_families.update(x['family'] for x in future_io(item['run_id']))
    state = {'schema': 1, 'status': 'running', 'budget_effective': INITIAL_EFFECTIVE,
             'max_faults': INITIAL_MAX_FAULTS, 'max_attempts': MAX_ATTEMPTS,
             'effective_count': sum(x['effective'] for x in pilot['results']),
             'next_trial': 1, 'pending': [], 'inflight': None,
             'results': [], 'seen_plans': [[x] for x in pilot['queue']],
             'seen_coverage': sorted(set().union(*(
                 set((ROOT / x / 'coverage.tsv').read_text().splitlines())
                 for x in ('healthy-a', 'healthy-b')
             ), *(set(x['coverage']) for x in pilot['results'] if x['effective']))),
             'seen_families': sorted(observed_families),
             'extended': False, 'pilot_selected': len(pilot['results']),
             'pilot_effective': sum(x['effective'] for x in pilot['results']),
             'pilot_effective_results': [
                 {'run_id': x['run_id'], 'new_coverage_lines': x['new_coverage_lines'],
                  'new_io_families': 0} for x in pilot['results'] if x['effective']],
             'source_commit':
                 json.loads((ROOT / 'healthy-a/run.json').read_text())['original_source_commit'],
             'agent_sha256': base.sha(base.AGENT), 'started_at': time.time()}
    for item in cal['healthy'][0]['io_candidates']:
        if item['selector'] in stable:
            add(state, [item['selector']], 'healthy-a', 4.0)
    for item in pilot['results']:
        if not item['effective']:
            continue
        novelty = item['new_coverage_lines']
        for candidate in future_io(item['run_id']):
            add(state, item['plan'] + [candidate['selector']], item['run_id'],
                8.0 + min(novelty, 15) * 0.5)
    write_json(CHECKPOINT, state)
    return state


def choose(state):
    rnd = random.Random(state['next_trial'] * 17011)
    ranked = []
    for i, job in enumerate(state['pending']):
        depth = len(job['plan'])
        ranked.append((job['score'] + min(depth, 6) * 0.4 + rnd.random() * 2.0
                       + (len(state['pending']) - i) * .003, i))
    _, i = max(ranked)
    return state['pending'].pop(i)


def record(state, job, receipt):
    if receipt['plan'] != job['plan'] or receipt['agent_sha256'] != state['agent_sha256']:
        raise RuntimeError('immutable run plan or agent digest differs')
    result = base.audit_trial_generic(job['run_id'], job['plan'],
                                      set(state['seen_coverage']))
    result['parent'] = job['parent']
    result['fault_count'] = len(job['plan'])
    result['bug_mark'] = ('candidate_needs_source_review'
                          if result['selected_target_throws'] else 'none')
    result['new_io_families'] = 0
    if result['effective']:
        state['effective_count'] += 1
        state['seen_coverage'] = sorted(set(state['seen_coverage']) |
                                        set(result['coverage']))
        mutations = future_io(job['run_id'])
        families = {x['family'] for x in mutations}
        result['new_io_families'] = len(families - set(state['seen_families']))
        state['seen_families'] = sorted(set(state['seen_families']) | families)
        if len(job['plan']) < state['max_faults']:
            distinct = set()
            selected = []
            for item in mutations:
                if item['family'] not in distinct:
                    selected.append(item)
                    distinct.add(item['family'])
            for item in mutations[-8:] + mutations[:4]:
                if item not in selected:
                    selected.append(item)
            for item in selected[:24]:
                add(state, job['plan'] + [item['selector']], job['run_id'],
                    (8.0 if result['new_coverage_lines'] else 2.0)
                    + min(result['new_coverage_lines'], 20) * .3)
    result.pop('coverage')
    state['results'].append(result)
    state['inflight'] = None
    with LEDGER.open('a') as stream:
        stream.write(json.dumps(result, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    write_json(CHECKPOINT, state)
    print(json.dumps({k: result[k] for k in ('run_id', 'effective',
          'new_coverage_lines', 'selected_target_throws', 'elapsed_seconds',
          'junit_exit', 'fault_count')} | {'effective_total': state['effective_count'],
                                         'pending': len(state['pending'])},
                     sort_keys=True), flush=True)


def recover(state):
    job = state['inflight']
    if not job:
        return
    dest = ROOT / job['run_id']
    if (dest / 'run.json').is_file():
        record(state, job, json.loads((dest / 'run.json').read_text()))
    elif dest.exists():
        raise RuntimeError('incomplete run evidence requires manual audit: ' + str(dest))
    else:
        state['pending'].insert(0, {k: v for k, v in job.items() if k != 'run_id'})
        state['inflight'] = None
        write_json(CHECKPOINT, state)


def should_extend(state):
    last = (state['pilot_effective_results'] +
            [x for x in state['results'] if x['effective']])[-8:]
    return len(last) == 8 and any(x['new_coverage_lines'] or x['new_io_families']
                                  for x in last)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--worker-id', type=int, default=14)
    parser.add_argument('--worker-count', type=int, default=16)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--max-new-trials', type=int, default=480)
    args = parser.parse_args()
    if args.max_new_trials < 1:
        parser.error('max-new-trials must be positive')
    if not args.run:
        print(json.dumps({'status': 'prepared_only', 'budget': '80 effective/max8;'
                          ' conditional 128/max10', 'max_attempts': MAX_ATTEMPTS}))
        return
    base.verify_assets()
    HERE.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else initial_state()
        if state['agent_sha256'] != base.sha(base.AGENT):
            raise RuntimeError('campaign agent changed')
        if state['status'] not in ('running', 'paused_trial_limit', 'paused_resource_gate'):
            print(json.dumps({'status': state['status'],
                              'effective_count': state['effective_count']}))
            return
        recover(state)
        first_trial = state['next_trial']
        while True:
            if state['effective_count'] >= state['budget_effective']:
                if not state['extended'] and should_extend(state):
                    state['extended'] = True
                    state['budget_effective'] = EXTENDED_EFFECTIVE
                    state['max_faults'] = EXTENDED_MAX_FAULTS
                    write_json(CHECKPOINT, state)
                    continue
                state['status'] = 'budget_complete'
                break
            if state['next_trial'] - first_trial >= args.max_new_trials:
                state['status'] = 'paused_trial_limit'
                break
            if state['pilot_selected'] + len(state['results']) >= MAX_ATTEMPTS:
                state['status'] = 'attempt_cap'
                break
            if not state['pending']:
                state['status'] = 'queue_exhausted'
                break
            job = choose(state)
            job['run_id'] = 'campaign-{:04d}'.format(state['next_trial'])
            state['next_trial'] += 1
            state['inflight'] = job
            write_json(CHECKPOINT, state)
            try:
                receipt = base.run_one(job['run_id'], job['plan'], args.worker_id,
                                       args.worker_count, args.timeout)
            except RuntimeError as error:
                if str(error).startswith('resource gate:'):
                    state['pending'].insert(0, {k: v for k, v in job.items()
                                                if k != 'run_id'})
                    state['inflight'] = None
                    state['status'] = 'paused_resource_gate'
                    state['pause_reason'] = str(error)
                    break
                raise
            record(state, job, receipt)
        write_json(CHECKPOINT, state)
        print(json.dumps({'status': state['status'],
                          'effective_count': state['effective_count'],
                          'budget_effective': state['budget_effective'],
                          'max_faults': state['max_faults'],
                          'attempts': state['pilot_selected'] + len(state['results']),
                          'campaign_attempts': len(state['results']),
                          'pending': len(state['pending'])}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
