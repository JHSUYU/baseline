#!/usr/bin/env python3
"""Checkpointed, graph-free SOLR-18 original-JUnit alias-ZK campaign."""
from __future__ import annotations
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import signal

from run_native import RUN_ROOT, run

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
STATE = HERE / 'evidence/campaign-state.json'
LEDGER = HERE / 'trial-ledger.jsonl'
HEALTHY = RUN_ROOT / 'healthy-instrumented'
STOP = False


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def events(run_id):
    path = RUN_ROOT / run_id / 'events.tsv'
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        fields = line.split('\t')
        if len(fields) >= 3:
            rows.append((int(fields[0]), fields[1], fields[2], fields[3:]))
    return sorted(rows)


def selector(row):
    return row[3][0] + '@@' + row[3][1]


def selected_guard(trace):
    started = next((row for row in trace if row[1] == 'TEST_STARTED'), None)
    if started is None:
        return None
    first_apply = next((row for row in trace if row[1] == 'APPLY_MODIFICATION'
                        and row[0] > started[0] and row[2].startswith('TEST-')
                        and len(row[3]) >= 2 and row[3][1] == 'TEST_BODY'), None)
    if first_apply is None:
        return None
    finished = next((row[0] for row in trace if row[1] == 'TEST_FINISHED'), None)
    next_apply = next((row[0] for row in trace if row[1] == 'APPLY_MODIFICATION'
                       and row[0] > first_apply[0] and row[3][0] == first_apply[3][0]), None)
    for row in trace:
        if (row[1] == 'TARGET_EQUAL_CHECK' and row[0] > first_apply[0]
                and (finished is None or row[0] < finished)
                and (next_apply is None or row[0] < next_apply)
                and row[3][0] == first_apply[3][0]
                and row[3][3:6] == ['1', '1', '0']):
            return row
    return None


def candidates(trace, after=0):
    target = selected_guard(trace)
    if target is None or target[0] <= after:
        return []
    started = next(row[0] for row in trace if row[1] == 'TEST_STARTED')
    return list(dict.fromkeys(selector(x) for x in trace
                              if x[1] == 'IO' and max(after, started) < x[0] < target[0]))


def mutation_candidates(items):
    if len(items) <= 12:
        return items
    selected, families = [], set()
    for item in items:
        family = item.split('@@')[0]
        if family not in families:
            selected.append(item)
            families.add(family)
    for item in items[-8:] + items[:4]:
        if item not in selected:
            selected.append(item)
    return selected[:20]


def feedback_priority(plan):
    site = plan[-1]
    if ':TEST@@' in site:
        family = 0
    elif '/overseer_elect/leader:' in site:
        family = 6
    elif '/overseer/collection-queue-work/' in site or '/overseer/queue' in site:
        family = 5
    elif '/aliases.json:' in site:
        family = 4
    elif '/counter:' in site:
        family = 2
    elif '/state.json:' in site:
        family = 1
    else:
        family = 3
    return family, len(plan)


def covered(run_id, suffix):
    p = RUN_ROOT / run_id / ('covered_' + suffix + '.txt')
    return set(p.read_text().splitlines()) if p.exists() else set()


HEALTHY_PROBES = covered('healthy-instrumented', 'probes')
HEALTHY_METHODS = covered('healthy-instrumented', 'methods')
HEALTHY_LINES = covered('healthy-instrumented', 'lines')


def analyze(job, metadata):
    trace = events(job['run_id'])
    matched = [selector(x) for x in trace if x[1] == 'FAULT_MATCHED']
    applied_events = [x for x in trace if x[1] == 'FAULT_APPLIED']
    applied = [selector(x) for x in applied_events]
    strict = matched == job['plan'] and applied == job['plan']
    last_fault = applied_events[-1][0] if applied_events else 0
    target = selected_guard(trace)
    retained = bool(strict and target is not None and target[0] > last_fault)
    selected_throw = [x for x in trace if x[1] == 'TARGET_THROW'
                      and target is not None and x[3][:6] == target[3][:6]
                      and x[0] > last_fault]
    all_throw = [x for x in trace if x[1] == 'TARGET_THROW']
    probes = covered(job['run_id'], 'probes')
    methods = covered(job['run_id'], 'methods')
    lines = covered(job['run_id'], 'lines')
    return {
        'run_id': job['run_id'], 'parent': job.get('parent'), 'plan': job['plan'],
        'fault_count': len(job['plan']), 'matched': matched, 'applied': applied,
        'strict_ordered_injection': strict,
        'selected_equal_check_after_final_fault': retained,
        'selected_equal_context': target[3] if target else None,
        'selected_equal_sequence': target[0] if target else None,
        'selected_json_equal': target[3][6] == 'true' if target else None,
        'selected_throw_after_fault_count': len(selected_throw),
        'selected_throw_events': [x[3] for x in selected_throw],
        'all_target_throw_count': len(all_throw),
        'all_target_throw_events': [x[3] for x in all_throw],
        'healthy_expected_target_throw_count': 0,
        'junit_exit': metadata['junit_exit'], 'elapsed_seconds': metadata['elapsed_seconds'],
        'assumption_failure_count': metadata['assumption_failure_count'],
        'junit_summary_present': metadata['junit_summary_present'],
        'test_started_count': metadata['test_started_count'],
        'new_production_probes_vs_healthy': sorted(probes - HEALTHY_PROBES),
        'new_production_methods_vs_healthy': sorted(methods - HEALTHY_METHODS),
        'new_production_lines_vs_healthy': sorted(lines - HEALTHY_LINES),
        'candidate_pretarget_io': candidates(trace, last_fault) if retained else [],
        'junit_differs_from_healthy': metadata['junit_exit'] != 0,
        'needs_source_review': bool((retained and (metadata['junit_exit'] != 0
                                  or metadata['assumption_failure_count'] != 0
                                  or not metadata['junit_summary_present']
                                  or len(selected_throw) != 0 or target[3][6] != 'true'))
                                  or all_throw),
        'bug_mark': 'none',
    }


def update_result(state):
    doc = json.loads(RESULT.read_text())
    trials = state['trials']
    strict = [x for x in trials if x['strict_ordered_injection']]
    valid = [x for x in trials if x['selected_equal_check_after_final_fault']]
    probes = set().union(*(set(x['new_production_probes_vs_healthy']) for x in valid)) if valid else set()
    methods = set().union(*(set(x['new_production_methods_vs_healthy']) for x in valid)) if valid else set()
    lines = set().union(*(set(x['new_production_lines_vs_healthy']) for x in valid)) if valid else set()
    doc.update({
        'status': 'fuzzing' if not state['finished'] else state.get('final_status', 'pending_source_review'),
        'methodology': 'original_cluster_junit_case_local_asm_jacoco_graph_free',
        'target_reached': True,
        'fault_trials': len(trials), 'strict_injections': len(strict),
        'fully_applied_trials': len(strict), 'target_after_fault': len(valid),
        'effective_fault_trials': len(valid),
        'coverage_gain': len(probes), 'production_method_gain': len(methods),
        'production_line_gain': len(lines),
        'elapsed_seconds': round(state['healthy_elapsed_seconds']
                                 + sum(x['elapsed_seconds'] for x in trials), 3),
        'campaign_budget': state['budget'], 'campaign_budget_unit': 'strict_target_retaining_trials',
        'max_faults': state['max_faults'],
        'max_fault_depth_attempted': max((x['fault_count'] for x in trials), default=0),
        'healthy_expected_target_throw_count': 0,
        'selected_target_throw_after_fault_trials': sum(x['selected_throw_after_fault_count'] > 0 for x in valid),
        'junit_nonzero_trials': sum(x['junit_exit'] != 0 for x in trials),
        'target_retaining_junit_nonzero_trials': sum(x['junit_exit'] != 0 for x in valid),
        'stop_reason': state.get('stop_reason', ''),
        'late_new_coverage_or_io_signal': state.get('late_extension_signal'),
        'independent_evidence': 'independent/evidence/campaign-state.json',
        'last_trial': trials[-1] if trials else None,
        'bug_mark': 'none',
    })
    atomic_json(RESULT, doc)


def save(state):
    atomic_json(STATE, state)
    update_result(state)


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
    meta = json.loads((HEALTHY / 'run.json').read_text())
    trace = events('healthy-instrumented')
    guards = [x for x in trace if x[1] == 'TARGET_GUARD']
    throws = [x for x in trace if x[1] == 'TARGET_THROW']
    equal = [x for x in trace if x[1] == 'TARGET_EQUAL_CHECK']
    assert meta['junit_exit'] == 0 and meta['assumption_failure_count'] == 0
    assert meta['junit_summary_present'] and len(guards) == len(equal) == 13 and not throws
    assert selected_guard(trace) is not None and selected_guard(trace)[3][6] == 'true'
    seed = candidates(trace)
    assert seed
    by_family = {}
    for x in seed:
        by_family.setdefault(x.split('@@')[0], []).append(x)
    order = sorted(by_family, key=lambda x: (0 if 'setData' in x and ':TEST' in x
                                              else 1 if 'zkCallback' in x else 2, x))
    balanced = []
    while any(by_family.values()):
        for family in order:
            if by_family[family]:
                balanced.append(by_family[family].pop(0))
    state = {'schema_version': 1, 'budget': 80, 'budget_unit': 'strict_target_retaining_trials',
             'max_faults': 8, 'pending': [],
             'queued': [], 'trials': [], 'inflight_jobs': [], 'next_trial_number': 1,
             'seen_pretarget_io': seed,
             'healthy_elapsed_seconds': json.loads(RESULT.read_text())['healthy_elapsed_seconds'],
             'schedule_since_shallow': 0, 'finished': False}
    for x in balanced:
        enqueue(state, [x], 'healthy-instrumented')
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
    path = RUN_ROOT / job['run_id'] / 'run.json'
    if path.exists():
        old = json.loads(path.read_text())
        assert old['plan'] == job['plan']
        return old
    return run(job['run_id'], job['plan'], timeout=300)


def record(state, job, metadata):
    item = analyze(job, metadata)
    before = set(state['seen_pretarget_io'])
    state['seen_pretarget_io'] = sorted(before | set(item['candidate_pretarget_io']))
    item['new_pretarget_io_count'] = len(set(item['candidate_pretarget_io']) - before)
    if item['selected_equal_check_after_final_fault'] and len(job['plan']) < state['max_faults']:
        for x in reversed(mutation_candidates(item['candidate_pretarget_io'])):
            enqueue(state, job['plan'] + [x], job['run_id'], front=True)
    state['trials'].append(item)
    state['trials'].sort(key=lambda x: int(x['run_id'].split('-')[-1]))
    state['inflight_jobs'] = [x for x in state['inflight_jobs'] if x['run_id'] != job['run_id']]
    with LEDGER.open('a') as stream:
        stream.write(json.dumps(item, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    save(state)
    print('trial={} depth={} exit={} matched={}/{} strict={} equal-after={} selected-throw={} all-throws={} cov+={} io+={} elapsed={:.3f}s'.format(
        job['run_id'], len(job['plan']), item['junit_exit'], len(item['matched']),
        len(job['plan']), item['strict_ordered_injection'], item['selected_equal_check_after_final_fault'],
        item['selected_throw_after_fault_count'], item['all_target_throw_count'],
        len(item['new_production_probes_vs_healthy']), item['new_pretarget_io_count'],
        item['elapsed_seconds']), flush=True)


def late_signal(state):
    probes = set(HEALTHY_PROBES)
    methods, lines = set(HEALTHY_METHODS), set(HEALTHY_LINES)
    healthy_runs = ['healthy-instrumented']
    if state.get('expanded_healthy_run'):
        healthy_runs.append(state['expanded_healthy_run'])
    families = {x.split('@@')[0] for name in healthy_runs
                for x in candidates(events(name))}
    first, observations = {}, {}
    late_probes, late_methods, late_lines = [], [], []
    valid_index = 0
    for item in state['trials']:
        if not item['selected_equal_check_after_final_fault']:
            continue
        valid_index += 1
        run_probes = covered(item['run_id'], 'probes')
        run_methods = covered(item['run_id'], 'methods')
        run_lines = covered(item['run_id'], 'lines')
        if valid_index > 72:
            late_probes.extend({'trial': item['run_id'], 'probe': x}
                               for x in sorted(run_probes - probes))
            late_methods.extend({'trial': item['run_id'], 'method': x}
                                for x in sorted(run_methods - methods))
            late_lines.extend({'trial': item['run_id'], 'line': x}
                              for x in sorted(run_lines - lines))
        probes |= run_probes
        methods |= run_methods
        lines |= run_lines
        for family in {x.split('@@')[0] for x in item['candidate_pretarget_io']}:
            if family not in families:
                first[family] = valid_index
                families.add(family)
            if family in first:
                observations[family] = observations.get(family, 0) + 1
    stable = [{'family': x, 'first_trial': first[x], 'valid_observations': observations[x]}
              for x in first if first[x] > 72 and observations.get(x, 0) >= 2]
    return {'late_new_production_probes': late_probes,
            'late_new_production_methods': late_methods,
            'late_new_production_lines_requiring_source_review': late_lines,
            'late_stable_new_io_families': stable,
            'extend': bool(late_probes or late_methods or late_lines or stable)}


def finish_or_extend(state):
    valid_count = sum(x['selected_equal_check_after_final_fault'] for x in state['trials'])
    if state['pending'] and valid_count < state['budget']:
        return False
    if valid_count >= state['budget']:
        state['late_extension_signal'] = late_signal(state)
        state['stop_reason'] = '80_effective_trial_budget_complete'
    else:
        state['stop_reason'] = 'observed_io_feedback_frontier_exhausted_before_effective_budget'
    state['finished'] = True
    state['final_status'] = 'pending_source_review' if valid_count >= state['budget'] else 'incomplete_frontier_exhausted'
    save(state)
    return True


def request_stop(signum, frame):
    global STOP
    STOP = True
    print('graceful stop requested; draining active JUnits', flush=True)


def main():
    signal.signal(signal.SIGUSR1, request_stop)
    state = json.loads(STATE.read_text()) if STATE.exists() else initial_state()
    recover(state)
    active = {}
    with ThreadPoolExecutor(max_workers=1) as pool:
        while not state['finished']:
            valid_count = sum(x['selected_equal_check_after_final_fault'] for x in state['trials'])
            while not STOP and state['pending'] and len(active) < 1 and valid_count < state['budget']:
                recovered = next((i for i, x in enumerate(state['pending']) if x.get('run_id')), None)
                shallow = next((i for i, x in enumerate(state['pending']) if len(x['plan']) == 1), None)
                feedback = [i for i, item in enumerate(state['pending']) if len(item['plan']) > 1]
                max_depth_seen = max((item['fault_count'] for item in state['trials']), default=0)
                if feedback and max_depth_seen >= state['max_faults']:
                    deepest = max(feedback, key=lambda i: feedback_priority(state['pending'][i]['plan']))
                else:
                    deepest = max(range(len(state['pending'])), key=lambda i: len(state['pending'][i]['plan']))
                index = recovered if recovered is not None else (
                    shallow if shallow is not None and state['schedule_since_shallow'] >= 2
                    else deepest)
                pending = state['pending'].pop(index)
                state['schedule_since_shallow'] = 0 if len(pending['plan']) == 1 else min(2, state['schedule_since_shallow'] + 1)
                run_id = pending.get('run_id')
                if run_id is None:
                    run_id = 'trial-{:03d}'.format(state['next_trial_number'])
                    state['next_trial_number'] += 1
                job = {'run_id': run_id, 'plan': pending['plan'], 'parent': pending.get('parent')}
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
                record(state, job, future.result())


if __name__ == '__main__':
    main()
