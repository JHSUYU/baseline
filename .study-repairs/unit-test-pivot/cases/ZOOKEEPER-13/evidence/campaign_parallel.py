#!/usr/bin/env python3
"""Two original-JUnit workers with disjoint ZooKeeper PortAssignment ranges."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
from pathlib import Path
import os
import signal

from campaign import (CHECKPOINT, LEDGER, ROOT, analyze, candidate_io,
                      events, late_extension_signal, save)
from run_native import run

WORKERS = (7, 8)
PORT_ASSIGNMENT_PROCESS_COUNT = 8
STOP_REQUESTED = False


def request_stop(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print('graceful stop requested; waiting for active original JUnit runs', flush=True)


def number(run_id):
    return int(run_id.split('-')[-1])


def execute(job):
    run_id, plan, worker = job['run_id'], job['plan'], job['worker_id']
    path = ROOT / run_id / 'run.json'
    if path.exists():
        result = json.loads(path.read_text())
        assert result['plan'] == plan
        if result['exit_code'] != 130:
            return result
        path.unlink()
    return run(run_id, plan, worker_id=worker,
               worker_count=PORT_ASSIGNMENT_PROCESS_COUNT)


def recover(state):
    old = state.pop('inflight', None)
    jobs = list(state.pop('inflight_jobs', []))
    if old:
        jobs.append(old)
    for job in sorted(jobs, key=lambda x: number(x['run_id']), reverse=True):
        state['pending'].insert(0, {'plan': job['plan'],
                                    'parent': 'recovered',
                                    'run_id': job['run_id']})
    all_numbers = [number(t['run_id']) for t in state['trials']]
    all_numbers += [number(x['run_id']) for x in state['pending'] if x.get('run_id')]
    state['next_trial_number'] = max(
        state.get('next_trial_number', 1),
        max(all_numbers, default=0) + 1)
    state['trials'].sort(key=lambda x: number(x['run_id']))
    state['scheduler'] = 'two_junit_workers_disjoint_port_ranges'
    save(state)


def record(state, job, result):
    trial = analyze(job['run_id'], job['plan'], result)
    seen = set(state['seen_pretarget_io'])
    state['seen_pretarget_io'] = sorted(seen | set(trial['candidate_pretarget_io']))
    trial['new_pretarget_io_count'] = len(set(trial['candidate_pretarget_io']) - seen)
    trial['worker_id'] = result.get('port_assignment_worker_id', job['worker_id'])
    if trial['target_after_final_fault'] and len(job['plan']) < state['max_faults']:
        queued = {tuple(x) for x in state['queued']}
        additions = []
        for candidate in trial['candidate_pretarget_io']:
            new_plan = tuple(job['plan'] + [candidate])
            if new_plan not in queued:
                additions.append({'plan': list(new_plan), 'parent': job['run_id']})
                state['queued'].append(list(new_plan))
                queued.add(new_plan)
        state['pending'] = additions + state['pending']
    state['trials'].append(trial)
    state['trials'].sort(key=lambda x: number(x['run_id']))
    state['inflight_jobs'] = [x for x in state['inflight_jobs']
                              if x['run_id'] != job['run_id']]
    with LEDGER.open('a') as output:
        output.write(json.dumps(trial, sort_keys=True) + '\n')
        output.flush()
        os.fsync(output.fileno())
    save(state)
    print('trial={} worker={} depth={} exit={} strict={} target_after={} valid_coverage={} elapsed={:.3f}s'.format(
        job['run_id'], job['worker_id'], len(job['plan']), trial['junit_exit'],
        trial['strict_injection'], trial['target_after_final_fault'],
        trial['new_production_coverage_lines'], trial['elapsed_seconds']), flush=True)


def maybe_finish_or_extend(state):
    if len(state['trials']) < state['budget'] and state['pending']:
        return False
    if len(state['trials']) >= state['budget']:
        signal = late_extension_signal(state) if state['budget'] == 80 else None
        if signal is not None:
            state['late_extension_signal'] = signal
        if state['budget'] == 80 and signal['extend']:
            state['budget'] = 128
            state['max_faults'] = 10
            queued = {tuple(x) for x in state['queued']}
            for previous in state['trials']:
                if previous['fault_count'] == 8 and previous['target_after_final_fault']:
                    for candidate in previous['candidate_pretarget_io']:
                        plan = tuple(previous['plan'] + [candidate])
                        if plan not in queued:
                            state['pending'].append({'plan': list(plan),
                                                     'parent': previous['run_id']})
                            state['queued'].append(list(plan))
                            queued.add(plan)
            save(state)
            return False
        state.update(finished=True, final_status='quality_complete',
                     stop_reason='80_trial_budget_complete_no_late_valid_new_method_or_stable_io_family'
                     if state['budget'] == 80 else '128_trial_budget_complete')
    else:
        state.update(finished=True, final_status='quality_complete',
                     stop_reason='observed_pretarget_io_selector_frontier_exhausted')
    save(state)
    return True


def main():
    signal.signal(signal.SIGUSR1, request_stop)
    state = json.loads(CHECKPOINT.read_text())
    recover(state)
    active = {}
    with ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
        while not state['finished']:
            while not STOP_REQUESTED and state['pending'] and len(active) < len(WORKERS):
                if len(state['trials']) + len(active) >= state['budget'] and not any(
                        item.get('run_id') for item in state['pending']):
                    break
                shallow_index = next((i for i, item in enumerate(state['pending'])
                                      if len(item['plan']) == 1), None)
                prefer_shallow = state.get('schedule_since_shallow', 0) >= 2
                deepest_index = max(range(len(state['pending'])),
                                    key=lambda i: len(state['pending'][i]['plan']))
                recovered_index = next((i for i, item in enumerate(state['pending'])
                                        if item.get('run_id')), None)
                index = (recovered_index if recovered_index is not None else
                         shallow_index if prefer_shallow and shallow_index is not None else
                         deepest_index)
                if len(state['trials']) + len(active) >= state['budget'] and not state['pending'][index].get('run_id'):
                    index = next(i for i, item in enumerate(state['pending']) if item.get('run_id'))
                item = state['pending'].pop(index)
                state['schedule_since_shallow'] = 0 if len(item['plan']) == 1 else min(
                    state.get('schedule_since_shallow', 0) + 1, 2)
                used = {job['worker_id'] for job in active.values()}
                worker = next(w for w in WORKERS if w not in used)
                run_id = item.get('run_id')
                if not run_id:
                    run_id = 'trial-{:03d}'.format(state['next_trial_number'])
                    state['next_trial_number'] += 1
                job = {'run_id': run_id, 'plan': item['plan'],
                       'parent': item.get('parent'), 'worker_id': worker}
                state.setdefault('inflight_jobs', []).append(job)
                save(state)
                active[pool.submit(execute, job)] = job
            if not active:
                if STOP_REQUESTED:
                    save(state)
                    break
                if maybe_finish_or_extend(state):
                    break
                continue
            completed, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in completed:
                job = active.pop(future)
                result = future.result()
                if result['exit_code'] == 130:
                    (ROOT / job['run_id'] / 'run.json').unlink(missing_ok=True)
                    state['inflight_jobs'] = [x for x in state['inflight_jobs']
                                              if x['run_id'] != job['run_id']]
                    state['pending'].insert(0, {'plan': job['plan'],
                                                'parent': job.get('parent'),
                                                'run_id': job['run_id']})
                    save(state)
                    continue
                record(state, job, result)


if __name__ == '__main__':
    main()
