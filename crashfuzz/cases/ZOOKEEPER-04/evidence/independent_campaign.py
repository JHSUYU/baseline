#!/usr/bin/env python3
"""Checkpointed graph-independent, exact-selector ZooKeeper-04 campaign."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import signal

from independent_run import ROOT, run

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
CHECKPOINT = HERE / 'independent-checkpoint.json'
LEDGER = HERE / 'independent-trials.jsonl'
WORKERS = (7, 8)
STOP = False
HEALTHY = set((ROOT / 'healthy-01/coverage.tsv').read_text().splitlines())
HEALTHY_METHODS = {'\t'.join(x.split('\t')[:2]) for x in HEALTHY}


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def events(run_id):
    path = ROOT / run_id / 'events.tsv'
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        fields = line.split('\t')
        if len(fields) >= 4:
            result.append((int(fields[0]), fields[1], fields[2], fields[3:]))
    return sorted(result)


def selector(event):
    return event[3][0] + '@@' + event[3][1]


def candidates(trace, after=0):
    guards = [x[0] for x in trace if x[1] == 'TARGET_GUARD' and x[0] > after]
    if not guards:
        return []
    before = max(guards)
    return list(dict.fromkeys(selector(x) for x in trace
                              if x[1] == 'IO' and after < x[0] < before))


def trial_analysis(job, result):
    trace = events(job['run_id'])
    matches = [selector(x) for x in trace if x[1] == 'FAULT_MATCHED']
    applied_events = [x for x in trace if x[1] == 'FAULT_APPLIED']
    applied = [selector(x) for x in applied_events]
    strict = matches == job['plan'] and applied == job['plan']
    last = applied_events[-1][0] if applied_events else 0
    guards = [x for x in trace if x[1] == 'TARGET_GUARD' and x[0] > last]
    throws = [x for x in trace if x[1] == 'TARGET_THROW' and x[0] > last]
    cov_path = ROOT / job['run_id'] / 'coverage.tsv'
    cov = set(cov_path.read_text().splitlines()) if cov_path.exists() else set()
    retained = bool(strict and guards)
    return {
        'run_id': job['run_id'], 'parent': job.get('parent'),
        'worker_id': job['worker_id'], 'plan': job['plan'],
        'fault_count': len(job['plan']), 'elapsed_seconds': result['elapsed_seconds'],
        'junit_exit': result['exit_code'], 'matched': matches, 'applied': applied,
        'strict_injection': strict, 'target_after_final_fault': retained,
        'target_guard_after_fault_count': len(guards),
        'target_guard_arms_after_fault': [x[3][0] for x in guards],
        'target_throw_after_fault_count': len(throws),
        'target_throw_total_count': sum(x[1] == 'TARGET_THROW' for x in trace),
        'target_exception': 'CloseRequestException(CLIENT_ZXID_AHEAD)' if throws else None,
        'target_exception_source_review': 'ZooKeeperServer.processConnectRequest:1431-1441',
        'junit_outcome_differs_from_healthy': result['exit_code'] != 0,
        'new_production_coverage': sorted(cov - HEALTHY),
        'new_production_coverage_lines': len(cov - HEALTHY),
        'candidate_pretarget_io': candidates(trace, last) if retained else [],
        'bug_mark': 'none',
    }


def update_result(state):
    doc = json.loads(RESULT.read_text())
    trials = state['trials']
    strict = [x for x in trials if x['strict_injection']]
    retained = [x for x in trials if x['target_after_final_fault']]
    admitted = set().union(*(set(x['new_production_coverage']) for x in retained)) if retained else set()
    all_cov = set().union(*(set(x['new_production_coverage']) for x in trials)) if trials else set()
    doc.update({
        'status': state.get('final_status', 'quality_complete') if state['finished'] else 'fuzzing',
        'target_reached': True,
        'methodology': 'original_cluster_junit_case_local_asm_independent_recorder',
        'fault_trials': len(trials), 'strict_injections': len(strict),
        'fully_applied_trials': len(strict), 'target_after_fault': len(retained),
        'coverage_gain': len(admitted), 'coverage_gain_all_attempts': len(all_cov),
        'elapsed_seconds': round(16.192 + 5.21 + sum(x['elapsed_seconds'] for x in trials), 3),
        'trial_elapsed_seconds': round(sum(x['elapsed_seconds'] for x in trials), 3),
        'campaign_budget': state['budget'], 'max_faults': state['max_faults'],
        'max_fault_depth_attempted': max((x['fault_count'] for x in trials), default=0),
        'campaign_finished': state['finished'], 'stop_reason': state.get('stop_reason', ''),
        'bug_mark': state.get('bug_mark', 'none'),
        'healthy_guard_count': 2, 'healthy_target_throw_count': 0,
        'positive_control_throw_count': 1,
        'new_methodology_run_root': str(ROOT),
        'last_trial': trials[-1] if trials else None,
    })
    atomic_json(RESULT, doc)


def save(state):
    atomic_json(CHECKPOINT, state)
    update_result(state)


def late_extension_signal(state):
    methods = set(HEALTHY_METHODS)
    healthy_families = {x.split('@@')[0] for x in candidates(events('healthy-01'))}
    families = set(healthy_families)
    first = {}
    count = {}
    late_methods = []
    for number, item in enumerate(state['trials'], 1):
        if not item['target_after_final_fault']:
            continue
        path = ROOT / item['run_id'] / 'coverage.tsv'
        cov = set(path.read_text().splitlines()) if path.exists() else set()
        observed_methods = {'\t'.join(x.split('\t')[:2]) for x in cov}
        if number > 72:
            late_methods.extend({'trial': item['run_id'], 'method': x}
                                for x in sorted(observed_methods - methods))
        methods |= observed_methods
        observed_families = {x.split('@@')[0] for x in item['candidate_pretarget_io']}
        for family in observed_families:
            if family not in families:
                first[family] = number
                families.add(family)
            if family in first:
                count[family] = count.get(family, 0) + 1
    stable_late = [{'family': x, 'first_trial': first[x], 'valid_observations': count[x]}
                   for x in sorted(first) if first[x] > 72 and count[x] >= 2]
    return {'late_new_production_methods': late_methods,
            'late_stable_new_io_families': stable_late,
            'extend': bool(late_methods or stable_late)}


def enqueue(state, plan, parent, front=False):
    key = tuple(plan)
    if key in {tuple(x) for x in state['queued']}:
        return
    state['queued'].append(list(plan))
    item = {'plan': list(plan), 'parent': parent}
    if front:
        state['pending'].insert(0, item)
    else:
        state['pending'].append(item)


def initial_state():
    healthy = events('healthy-01')
    assert sum(x[1] == 'TARGET_GUARD' for x in healthy) == 2
    assert not any(x[1] == 'TARGET_THROW' for x in healthy)
    positive = events('positive-control-01')
    assert any(x[1] == 'TARGET_THROW' and x[3] == ['CLIENT_ZXID_AHEAD'] for x in positive)
    seed = candidates(healthy)
    seed.sort(key=lambda x: (0 if 'ClientCnxnSocketNIO' in x else 1, x))
    state = {'schema_version': 1, 'budget': 80, 'max_faults': 8,
             'pending': [], 'queued': [], 'trials': [], 'inflight_jobs': [],
             'next_trial_number': 1, 'seen_pretarget_io': seed,
             'schedule_since_shallow': 0, 'finished': False, 'bug_mark': 'none'}
    for x in seed:
        enqueue(state, [x], 'healthy-01')
    save(state)
    return state


def recover(state):
    for job in sorted(state.pop('inflight_jobs', []),
                      key=lambda x: int(x['run_id'].split('-')[-1]), reverse=True):
        state['pending'].insert(0, {'plan': job['plan'], 'parent': job.get('parent'),
                                    'run_id': job['run_id']})
    state['inflight_jobs'] = []
    save(state)


def run_job(job):
    path = ROOT / job['run_id'] / 'run.json'
    if path.exists():
        result = json.loads(path.read_text())
        assert result['plan'] == job['plan']
        if result['exit_code'] != 130:
            return result
        path.unlink()
    return run(job['run_id'], job['plan'], worker_id=job['worker_id'], worker_count=8)


def record(state, job, result):
    item = trial_analysis(job, result)
    before = set(state['seen_pretarget_io'])
    state['seen_pretarget_io'] = sorted(before | set(item['candidate_pretarget_io']))
    item['new_pretarget_io_count'] = len(set(item['candidate_pretarget_io']) - before)
    if item['target_after_final_fault'] and len(job['plan']) < state['max_faults']:
        for x in reversed(item['candidate_pretarget_io']):
            enqueue(state, job['plan'] + [x], job['run_id'], front=True)
    state['trials'].append(item)
    state['trials'].sort(key=lambda x: int(x['run_id'].split('-')[-1]))
    state['inflight_jobs'] = [x for x in state['inflight_jobs'] if x['run_id'] != job['run_id']]
    with LEDGER.open('a') as out:
        out.write(json.dumps(item, sort_keys=True) + '\n')
        out.flush()
        os.fsync(out.fileno())
    save(state)
    print('trial={} depth={} exit={} matched={}/{} strict={} target_after={} throw={} coverage+={} io+={} elapsed={:.3f}s'.format(
        job['run_id'], len(job['plan']), item['junit_exit'], len(item['matched']),
        len(job['plan']), item['strict_injection'], item['target_after_final_fault'],
        item['target_throw_after_fault_count'], item['new_production_coverage_lines'],
        item['new_pretarget_io_count'], item['elapsed_seconds']), flush=True)


def finish_or_extend(state):
    if state['pending'] and len(state['trials']) < state['budget']:
        return False
    if len(state['trials']) >= state['budget']:
        signal_data = late_extension_signal(state) if state['budget'] == 80 else None
        state['late_extension_signal'] = signal_data
        if state['budget'] == 80 and signal_data['extend']:
            state['budget'], state['max_faults'] = 128, 10
            for old in state['trials']:
                if old['fault_count'] == 8 and old['target_after_final_fault']:
                    for x in old['candidate_pretarget_io']:
                        enqueue(state, old['plan'] + [x], old['run_id'])
            save(state)
            return False
        state['stop_reason'] = '80_trial_budget_complete_no_late_valid_new_method_or_stable_io_family' if state['budget'] == 80 else '128_trial_budget_complete'
    else:
        state['stop_reason'] = 'observed_pretarget_io_selector_frontier_exhausted'
    state['finished'] = True
    state['final_status'] = 'quality_complete'
    save(state)
    return True


def request_stop(signum, frame):
    global STOP
    STOP = True
    print('graceful stop requested; waiting for active JUnit runs', flush=True)


def main():
    signal.signal(signal.SIGUSR1, request_stop)
    state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else initial_state()
    recover(state)
    active = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        while not state['finished']:
            while not STOP and state['pending'] and len(active) < 2 and len(state['trials']) + len(active) < state['budget']:
                recovered = next((i for i, x in enumerate(state['pending']) if x.get('run_id')), None)
                shallow = next((i for i, x in enumerate(state['pending']) if len(x['plan']) == 1), None)
                deepest = max(range(len(state['pending'])), key=lambda i: len(state['pending'][i]['plan']))
                index = recovered if recovered is not None else (shallow if shallow is not None and state['schedule_since_shallow'] >= 2 else deepest)
                pending = state['pending'].pop(index)
                state['schedule_since_shallow'] = 0 if len(pending['plan']) == 1 else min(2, state['schedule_since_shallow'] + 1)
                used = {x['worker_id'] for x in active.values()}
                worker = next(x for x in WORKERS if x not in used)
                run_id = pending.get('run_id')
                if run_id is None:
                    run_id = 'trial-{:03d}'.format(state['next_trial_number'])
                    state['next_trial_number'] += 1
                job = {'run_id': run_id, 'plan': pending['plan'], 'parent': pending.get('parent'), 'worker_id': worker}
                state['inflight_jobs'].append(job)
                save(state)
                active[pool.submit(run_job, job)] = job
            if not active:
                if STOP:
                    save(state)
                    break
                if finish_or_extend(state):
                    break
                continue
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                job = active.pop(future)
                result = future.result()
                record(state, job, result)


if __name__ == '__main__':
    main()
