#!/usr/bin/env python3
"""Resume a bounded original-JUnit, coverage/I/O-guided checked-I/O campaign."""

import csv
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
STATE = HERE / 'checkpoint.json'
LEDGER = HERE / 'trials.json'
TABLE = HERE / 'trials.csv'
ROOT = '/users/ZhenyuLi/zk07-independent'
REMOTE = 'ZhenyuLi@node2'
SSH = ['ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes', '-o', 'IdentitiesOnly=yes',
       '-o', 'BatchMode=yes', REMOTE]
RSYNC_SHELL = 'ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes'
BASE_BUDGET = 80
EXTENDED_BUDGET = 128
BASE_MAX_FAULTS = 8
EXTENDED_MAX_FAULTS = 10


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    with os.fdopen(fd, 'w') as out:
        out.write(content)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def save_json(path, value):
    atomic(path, json.dumps(value, indent=2, sort_keys=True) + '\n')


def events(path):
    out = []
    for line in path.read_text().splitlines():
        parts = line.split('\t')
        if len(parts) >= 4:
            out.append({'seq': int(parts[0]), 'kind': parts[1],
                        'thread': parts[2], 'detail': parts[3:]})
    return out


def eligible_io(e):
    if e['kind'] != 'IO' or len(e['detail']) < 3:
        return False
    site = e['detail'][0]
    # The first LearnerHandler read precedes FOLLOWERINFO decoding. Its sid
    # field is still zero, so peer=0 would merge distinct live connections.
    if 'LearnerHandler#' in site and e['detail'][1] == 'peer=0':
        return False
    # Packet archives in Learner.writePacketNow/readPacket and LearnerHandler
    # use socket streams. QuorumPeer epoch helpers use disk files. A few
    # BinaryOutputArchive calls serialize only into memory; exclude those.
    return (site.startswith('org.apache.zookeeper.server.quorum.Learner#writePacketNow:')
            or site.startswith('org.apache.zookeeper.server.quorum.Learner#readPacket:')
            or site.startswith('org.apache.zookeeper.server.quorum.LearnerHandler#')
            or site.startswith('org.apache.zookeeper.server.quorum.QuorumPeer#readLongFromFile:')
            or site.startswith('org.apache.zookeeper.server.quorum.QuorumPeer#writeLongToFile:')
            or site.startswith('org.apache.zookeeper.server.quorum.Leader#')
            or site.startswith('org.apache.zookeeper.server.quorum.QuorumCnxManager#'))


def selector(e):
    return '@@'.join((e['detail'][0], e['detail'][1], e['detail'][2]))


def family(e):
    return 'IO@@' + e['detail'][0] + '@@' + e['detail'][1]


def coverage(path):
    return set(path.read_text().splitlines()) if path.exists() else set()


def initial_queue(seed_events):
    last_guard = max(e['seq'] for e in seed_events if e['kind'] == 'TARGET_GUARD')
    first_family = set()
    seen = set()
    queue = []
    for e in seed_events:
        if not eligible_io(e) or e['seq'] >= last_guard:
            continue
        exact = selector(e)
        if exact in seen:
            continue
        seen.add(exact)
        fam = family(e)
        score = 100 if fam not in first_family else 66
        first_family.add(fam)
        if '#readLongFromFile:' in exact or '#writeLongToFile:' in exact:
            score += 8
        if 'Learner#readPacket:' in exact or 'Learner#writePacketNow:' in exact:
            score += 6
        score += 4 * e['seq'] / last_guard
        queue.append({'plan': [exact], 'score': score, 'parent': 'healthy'})
    return queue


def read_run(run_id):
    local = HERE / 'trial-evidence' / run_id
    local.mkdir(parents=True, exist_ok=True)
    for name in ('events.tsv', 'coverage.tsv', 'lines.tsv', 'run.json'):
        src = REMOTE + ':' + ROOT + '/runs/' + run_id + '/' + name
        dst = str(local / name)
        proc = subprocess.run(['rsync', '-a', '-e', RSYNC_SHELL, src, dst],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise RuntimeError('cannot fetch {}: {}'.format(src, proc.stderr.strip()))
    return local


def run_plan(run_id, plan):
    remote_json = ROOT + '/plans/' + run_id + '.json'
    local_json = HERE / 'plans' / (run_id + '.json')
    save_json(local_json, plan)
    mkdir = subprocess.run(SSH + ['mkdir', '-p', ROOT + '/plans'],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if mkdir.returncode:
        raise RuntimeError(mkdir.stderr)
    transfer = subprocess.run(['rsync', '-a', '-e', RSYNC_SHELL, str(local_json),
                               REMOTE + ':' + remote_json],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if transfer.returncode:
        raise RuntimeError(transfer.stderr)
    exists = subprocess.run(SSH + ['test', '-f', ROOT + '/runs/' + run_id + '/run.json'])
    if exists.returncode != 0:
        partial = subprocess.run(SSH + ['test', '-d', ROOT + '/runs/' + run_id])
        if partial.returncode == 0:
            archive = ROOT + '/runs/' + run_id + '.interrupted-' + str(int(time.time()))
            moved = subprocess.run(SSH + ['mv', ROOT + '/runs/' + run_id, archive])
            if moved.returncode:
                raise RuntimeError('cannot preserve incomplete remote trial ' + run_id)
        command = SSH + ['python3', ROOT + '/tools/run_native.py', run_id,
                         '--plan', remote_json, '--timeout', '180']
        proc = subprocess.run(command, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
        print(proc.stdout.strip(), flush=True)
        if proc.returncode not in (0, 1, 124):
            print('remote execution returned {}: {}'.format(proc.returncode,
                                                            proc.stderr.strip()), flush=True)
    return read_run(run_id)


def analyze(run_id, plan, folder, union_cov, union_fam):
    ev = events(folder / 'events.tsv')
    result = json.loads((folder / 'run.json').read_text())
    applied = [e for e in ev if e['kind'] == 'FAULT_APPLIED']
    matched = [e for e in ev if e['kind'] == 'FAULT_MATCHED']
    identity_ambiguous = any('LearnerHandler#' in exact and '@@peer=0@@' in exact
                             for exact in plan)
    strict = not identity_ambiguous and len(matched) == len(applied) == len(plan)
    if strict:
        for idx, intended in enumerate(plan):
            for actual in (matched[idx], applied[idx]):
                if '@@'.join(actual['detail'][:3]) != intended or actual['detail'][3] != str(idx):
                    strict = False
            if matched[idx]['seq'] > applied[idx]['seq']:
                strict = False
        if any(applied[idx]['seq'] >= applied[idx + 1]['seq'] for idx in range(len(plan) - 1)):
            strict = False
    final_fault = applied[-1]['seq'] if strict else 10**18
    guards = [e for e in ev if e['kind'] == 'TARGET_GUARD']
    throws = [e for e in ev if e['kind'] == 'TARGET_THROW']
    post_target = strict and any(e['seq'] > final_fault for e in guards)
    post_throw = post_target and any(e['seq'] > final_fault for e in throws)
    cov = coverage(folder / 'coverage.tsv')
    eligible = [e for e in ev if eligible_io(e)]
    families = {family(e) for e in eligible}
    gain_cov = sorted(cov - union_cov) if post_target else []
    gain_family = sorted(families - union_fam) if post_target else []
    row = {'id': run_id, 'fault_plan': plan, 'fault_count': len(plan),
           'elapsed_seconds': result['elapsed_seconds'],
           'junit_exit_code': result['junit_exit_code'],
           'junit_timeout': result['timeout'],
           'exact_selector_matches': len(matched), 'applied_injections': len(applied),
           'strict_injection': strict,
           'identity_ambiguous': identity_ambiguous,
           'target_guard_anytime': bool(guards),
           'target_guard_after_final_fault': bool(post_target),
           'target_guard_normal_after_final_fault': sum(
               e['seq'] > final_fault and e['detail'][0] == 'NORMAL_ARM' for e in guards),
           'target_guard_throw_arm_after_final_fault': sum(
               e['seq'] > final_fault and e['detail'][0] == 'THROW_ARM' for e in guards),
           'exact_target_throw_after_final_fault': bool(post_throw),
           'new_production_jacoco_probes': len(gain_cov),
           'new_stable_io_families': len(gain_family),
           'new_io_family_keys': gain_family,
           'new_coverage_keys': gain_cov,
           'observed_eligible_io_events': len(eligible),
           'observed_eligible_io_families': len(families),
           'bug_mark': 'candidate_needs_source_review' if post_throw else 'none'}
    return row, ev, cov, families, final_fault


def children(row, ev, final_fault, max_faults):
    if not row['target_guard_after_final_fault'] or len(row['fault_plan']) >= max_faults:
        return []
    following_guards = [e['seq'] for e in ev if e['kind'] == 'TARGET_GUARD'
                        and e['seq'] > final_fault]
    if not following_guards:
        return []
    last_guard = max(following_guards)
    candidates = []
    family_seen = set()
    plan_family = {'IO@@' + '@@'.join(exact.split('@@')[:2]) for exact in row['fault_plan']}
    for e in ev:
        if not eligible_io(e) or not final_fault < e['seq'] < last_guard:
            continue
        fam = family(e)
        if fam in family_seen or fam in plan_family:
            continue
        family_seen.add(fam)
        exact = selector(e)
        bonus = row['new_production_jacoco_probes'] * 0.1 + row['new_stable_io_families'] * 2
        score = 85 + 22 * len(row['fault_plan']) + bonus
        if 'Learner#' in exact or '#readLongFromFile:' in exact:
            score += 9
        candidates.append({'plan': row['fault_plan'] + [exact], 'score': score,
                           'parent': row['id']})
    return candidates[:4]


def publish(state, seed_cov, seed_fam):
    rows = state['trials']
    save_json(STATE, state)
    save_json(LEDGER, {'case_id': 'ZOOKEEPER-07', 'methodology': 'coverage_io_no_graph',
                       'healthy_run': 'healthy-01', 'healthy_production_jacoco_probes': len(seed_cov),
                       'healthy_stable_io_families': len(seed_fam), 'trials': rows})
    columns = ['id', 'fault_count', 'elapsed_seconds', 'junit_exit_code',
               'exact_selector_matches', 'applied_injections', 'strict_injection',
               'target_guard_after_final_fault', 'exact_target_throw_after_final_fault',
               'new_production_jacoco_probes', 'new_stable_io_families', 'bug_mark']
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    atomic(TABLE, buf.getvalue())
    result = json.loads(RESULT.read_text())
    result.update(status='fuzzing' if len(rows) < state['budget'] else 'pending_source_review',
                  methodology='coverage_io_no_graph_independent_asm_jacoco',
                  healthy_run='independent/healthy/run.json',
                  healthy_target_guard_hits=sum(e['kind'] == 'TARGET_GUARD' for e in events(HERE / 'healthy/events.tsv')),
                  healthy_coverage_probes=len(seed_cov), healthy_io_families=len(seed_fam),
                  fault_trials=len(rows), strict_trials=sum(r['strict_injection'] for r in rows),
                  fully_applied_trials=sum(r['strict_injection'] for r in rows),
                  strict_injections=sum(r['applied_injections'] for r in rows if r['strict_injection']),
                  post_fault_target_reach_trials=sum(r['target_guard_after_final_fault'] for r in rows),
                  target_after_fault=sum(r['target_guard_after_final_fault'] for r in rows),
                  target_reached=True,
                  target_exception_after_fault_trials=sum(r['exact_target_throw_after_final_fault'] for r in rows),
                  admitted_coverage_gain=len(set(state['admitted_cov']) - seed_cov),
                  coverage_gain=len(set(state['admitted_cov']) - seed_cov),
                  admitted_new_io_families=len(set(state['admitted_families']) - seed_fam),
                  new_io_families=len(set(state['admitted_families']) - seed_fam),
                  trial_elapsed_seconds=round(sum(r['elapsed_seconds'] for r in rows), 3),
                  elapsed_seconds=round(json.loads((HERE / 'healthy/run.json').read_text())['elapsed_seconds']
                                        + sum(r['elapsed_seconds'] for r in rows), 3),
                  trial_ledger='independent/trials.json',
                  trial_table='independent/trials.csv',
                  baseline_trial_budget=state['budget'],
                  max_faults_per_sequence=state['max_faults'],
                  bug_mark='candidate_needs_source_review' if any(
                      r['bug_mark'] != 'none' for r in rows) else 'none')
    save_json(RESULT, result)


def main():
    seed_events = events(HERE / 'healthy/events.tsv')
    if not any(e['kind'] == 'TARGET_GUARD' for e in seed_events):
        raise RuntimeError('healthy run did not reach the exact target guard')
    seed_cov = coverage(HERE / 'healthy/coverage.tsv')
    seed_fam = {family(e) for e in seed_events if eligible_io(e)}
    if not seed_cov or not seed_fam:
        raise RuntimeError('missing independent healthy production coverage or I/O')
    if STATE.exists():
        state = json.loads(STATE.read_text())
    else:
        state = {'schema_version': 1, 'budget': BASE_BUDGET,
                 'max_faults': BASE_MAX_FAULTS, 'queue': initial_queue(seed_events),
                 'trials': [], 'admitted_cov': sorted(seed_cov),
                 'admitted_families': sorted(seed_fam), 'inflight': None,
                 'extended': False, 'started_at': time.time()}
        publish(state, seed_cov, seed_fam)
    while len(state['trials']) < state['budget']:
        if state['inflight'] is None:
            tested = {tuple(r['fault_plan']) for r in state['trials']}
            state['queue'] = [q for q in state['queue'] if tuple(q['plan']) not in tested]
            if not state['queue']:
                print('queue exhausted', flush=True)
                break
            # Deep sequences can become brittle after prior exceptions change
            # timing. Preserve them, but spend the bounded budget across fresh
            # sites when siblings repeatedly fail to apply their full plan.
            failed_by_parent = Counter(r['parent'] for r in state['trials']
                                       if not r['strict_injection'])
            def effective(q):
                return (q['score'] - 30 * max(0, len(q['plan']) - 3)
                        - 12 * failed_by_parent[q['parent']])
            state['queue'].sort(key=lambda q: (-effective(q), len(q['plan']), q['plan']))
            # Reserve part of the remaining budget for different initial
            # physical I/O families. A single successful prefix otherwise
            # fills the queue with its own descendants.
            single_families = {'@@'.join(r['fault_plan'][0].split('@@')[:2])
                               for r in state['trials'] if len(r['fault_plan']) == 1}
            reserve_seed = (len(state['trials']) >= 40 and len(single_families) < 20
                            and len(state['trials']) % 3 != 0)
            seed_index = next((i for i, q in enumerate(state['queue'])
                               if len(q['plan']) == 1
                               and '@@'.join(q['plan'][0].split('@@')[:2]) not in single_families),
                              None) if reserve_seed else None
            chosen = state['queue'].pop(seed_index if seed_index is not None else 0)
            run_id = 'trial-{:03d}'.format(len(state['trials']) + 1)
            state['inflight'] = {'id': run_id, **chosen}
            publish(state, seed_cov, seed_fam)
        current = state['inflight']
        local = run_plan(current['id'], current['plan'])
        row, ev, cov, families, final_fault = analyze(
            current['id'], current['plan'], local,
            set(state['admitted_cov']), set(state['admitted_families']))
        row['parent'] = current['parent']
        state['trials'].append(row)
        if row['target_guard_after_final_fault']:
            state['admitted_cov'] = sorted(set(state['admitted_cov']) | cov)
            state['admitted_families'] = sorted(set(state['admitted_families']) | families)
            current_plans = {tuple(q['plan']) for q in state['queue']}
            tested_plans = {tuple(r['fault_plan']) for r in state['trials']}
            for child in children(row, ev, final_fault, state['max_faults']):
                key = tuple(child['plan'])
                if key not in current_plans and key not in tested_plans:
                    state['queue'].append(child)
                    current_plans.add(key)
        state['inflight'] = None
        publish(state, seed_cov, seed_fam)
        print('{} faults={} strict={} target_after={} throw={} cov+={} io+={} {:.3f}s'.format(
            row['id'], row['fault_count'], row['strict_injection'],
            row['target_guard_after_final_fault'], row['exact_target_throw_after_final_fault'],
            row['new_production_jacoco_probes'], row['new_stable_io_families'],
            row['elapsed_seconds']), flush=True)
        if len(state['trials']) == BASE_BUDGET and not state['extended']:
            recent = state['trials'][-20:]
            if any(r['new_production_jacoco_probes'] or r['new_stable_io_families'] for r in recent):
                state['budget'] = EXTENDED_BUDGET
                state['max_faults'] = EXTENDED_MAX_FAULTS
                state['extended'] = True
                publish(state, seed_cov, seed_fam)
                print('extended to 128 trials/max10: independent late novelty', flush=True)
            else:
                print('stopped at 80: no independent coverage/I/O novelty in last 20', flush=True)
    result = json.loads(RESULT.read_text())
    if len(state['trials']) >= state['budget']:
        result['status'] = 'pending_source_review'
        result['stopping_reason'] = 'bounded independent campaign reached trial budget'
    else:
        result['status'] = 'pending_source_review'
        result['stopping_reason'] = 'observed exact selector queue exhausted'
    save_json(RESULT, result)


if __name__ == '__main__':
    main()
