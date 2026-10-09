#!/usr/bin/env python3
"""Checkpointed, exact-selector campaign for ZOOKEEPER-13."""

import json
import os
from pathlib import Path
import time

from run_native import ROOT, run

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
CHECKPOINT = HERE / 'campaign-checkpoint.json'
LEDGER = HERE / 'trials.jsonl'
HEALTHY_COVERAGE = set((ROOT / 'healthy-01/coverage.tsv').read_text().splitlines())
HEALTHY_METHODS = {'\t'.join(line.split('\t')[:2]) for line in HEALTHY_COVERAGE}
SOURCE_REVIEWED_BRANCH_BODIES = {
    'org.apache.zookeeper.server.NIOServerCnxn\tclose\t603':
        'NIOServerCnxn.java:602 if (!factory.removeCnxn(this)) true branch, return at 603',
    'org.apache.zookeeper.server.NIOServerCnxnFactory\tremoveCnxn\t766':
        'NIOServerCnxnFactory.java:765 if (!cnxns.remove(cnxn)) true branch, return false at 766',
}


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


def candidate_io(trace, after_seq=0):
    guards = [x[0] for x in trace if x[1] == 'TARGET_GUARD' and x[0] > after_seq]
    if not guards:
        return []
    before = max(guards)
    picks = [(x[0], selector(x)) for x in trace
             if x[1] == 'IO' and after_seq < x[0] < before]
    return list(dict.fromkeys(item for _, item in sorted(picks)))


def analyze(run_id, plan, run_result):
    trace = events(run_id)
    matches = [x for x in trace if x[1] == 'FAULT_MATCHED']
    applied = [x for x in trace if x[1] == 'FAULT_APPLIED']
    observed_matches = [selector(x) for x in matches]
    observed_applied = [selector(x) for x in applied]
    strict = observed_matches == list(plan) and observed_applied == list(plan)
    last_fault = applied[-1][0] if applied else 0
    guards = [x for x in trace if x[1] == 'TARGET_GUARD' and x[0] > last_fault]
    all_throws = [x for x in trace if x[1] == 'TARGET_THROW']
    throws = [x for x in all_throws if x[0] > last_fault]
    entries = [x for x in trace if x[1] == 'TARGET_ENTRY']
    throw_contexts = []
    for x in throws:
        entry = next((e for e in reversed(entries) if e[0] < x[0] and e[2] == x[2]), None)
        throw_contexts.append({
            'event_seq': x[0], 'thread': x[2],
            'site_reason_marker': x[3][0],
            'exception_class': x[3][1] if len(x[3]) > 1 else None,
            'observed_disconnect_reason': x[3][2] if len(x[3]) > 3 else None,
            'message': x[3][3] if len(x[3]) > 3 else (x[3][2] if len(x[3]) > 2 else None),
            'session_id_hex': entry[3][0] if entry and entry[3] else None,
            'remote_at_entry': entry[3][1] if entry and len(entry[3]) > 1 else None,
        })
    coverage_path = ROOT / run_id / 'coverage.tsv'
    coverage = set(coverage_path.read_text().splitlines()) if coverage_path.exists() else set()
    novel = sorted(coverage - HEALTHY_COVERAGE)
    candidates = candidate_io(trace, last_fault) if strict and guards else []
    return {
        'run_id': run_id, 'plan': list(plan), 'fault_count': len(plan),
        'elapsed_seconds': run_result['elapsed_seconds'],
        'junit_exit': run_result['exit_code'],
        'matched': observed_matches, 'applied': observed_applied,
        'strict_injection': strict,
        'target_after_final_fault': bool(strict and guards),
        'target_guard_after_fault_count': len(guards),
        'target_throw_after_fault_count': len(throws),
        'target_throw_total_count': len(all_throws),
        'target_throw_total_delta_vs_healthy': len(all_throws) - 9,
        'target_throw_contexts': throw_contexts,
        'target_throw_expected_in_healthy': True,
        'target_exception_matches_selected_source': all(
            x['exception_class'] == 'org.apache.zookeeper.server.ServerCnxn$CloseRequestException'
            and x['site_reason_marker'] == 'RENEW_GLOBAL_SESSION_IN_RO_MODE'
            and (x['observed_disconnect_reason'] in (None, 'RENEW_GLOBAL_SESSION_IN_RO_MODE'))
            for x in throw_contexts),
        'target_exception_source_review':
            'ReadOnlyZooKeeperServer.validateSession:123-126 throws CloseRequestException'
            ' with RENEW_GLOBAL_SESSION_IN_RO_MODE when isGlobalSession(sessionId)',
        'junit_outcome_differs_from_healthy': run_result['exit_code'] != 0,
        'needs_manual_review': bool(run_result['exit_code'] != 0 and strict and guards),
        'new_production_coverage_lines': len(novel),
        'new_production_coverage': novel,
        'candidate_pretarget_io': candidates,
        'candidate_pretarget_io_count': len(candidates),
        'bug_mark': 'none',
    }


def update_result(state):
    doc = json.loads(RESULT.read_text())
    trials = state['trials']
    strict = [x for x in trials if x['strict_injection']]
    retaining = [x for x in trials if x['target_after_final_fault']]
    union = set().union(*(set(x['new_production_coverage']) for x in retaining)) if retaining else set()
    all_attempt_union = set().union(*(set(x['new_production_coverage']) for x in trials)) if trials else set()
    doc.update(
        status='fuzzing' if not state.get('finished') else state.get('final_status', 'quality_complete'),
        elapsed_seconds=round(65.277 + sum(x['elapsed_seconds'] for x in trials), 3),
        fault_trials=len(trials), strict_injections=len(strict),
        fully_applied_trials=len(strict), target_after_fault=len(retaining),
        coverage_gain=len(union), coverage_gain_all_attempts=len(all_attempt_union),
        bug_mark='none',
        max_fault_depth_attempted=max((x['fault_count'] for x in trials), default=0),
        campaign_budget=state['budget'], max_faults=state['max_faults'],
        campaign_finished=bool(state.get('finished')),
        stop_reason=state.get('stop_reason', ''),
        last_trial=trials[-1] if trials else None,
    )
    atomic_json(RESULT, doc)


def save(state):
    atomic_json(CHECKPOINT, state)
    update_result(state)


def late_extension_signal(state):
    """Only accepted, target-retaining production novelty can extend 80 to 128."""
    trials = state['trials']
    threshold = 72
    seen_methods = set(HEALTHY_METHODS)
    seen_lines = set(HEALTHY_COVERAGE)
    healthy_io_families = {x.split('@@')[0] for x in candidate_io(events('healthy-01'))}
    seen_families = set(healthy_io_families)
    family_first = {}
    family_valid_count = {}
    late_methods = []
    late_branches = []
    for number, trial in enumerate(trials, 1):
        if not trial['target_after_final_fault']:
            continue
        coverage_file = ROOT / trial['run_id'] / 'coverage.tsv'
        coverage = coverage_file.read_text().splitlines() if coverage_file.exists() else []
        new_lines = set(coverage) - seen_lines
        if number > threshold:
            late_branches.extend({
                'trial': trial['run_id'], 'exclusive_body_line': line,
                'source_proof': SOURCE_REVIEWED_BRANCH_BODIES[line]}
                for line in sorted(new_lines) if line in SOURCE_REVIEWED_BRANCH_BODIES)
        seen_lines |= set(coverage)
        methods = {'\t'.join(line.split('\t')[:2]) for line in coverage}
        new_methods = methods - seen_methods
        if number > threshold:
            late_methods.extend({'trial': trial['run_id'], 'method': item}
                                for item in sorted(new_methods))
        seen_methods |= methods
        families = {x.split('@@')[0] for x in trial['candidate_pretarget_io']}
        for family in families:
            if family not in seen_families:
                family_first[family] = number
                seen_families.add(family)
            if family in family_first:
                family_valid_count[family] = family_valid_count.get(family, 0) + 1
    stable_late_families = [
        {'family': family, 'first_trial': family_first[family],
         'valid_trial_observations': family_valid_count[family]}
        for family in sorted(family_first)
        if family_first[family] > threshold and family_valid_count[family] >= 2
    ]
    return {'late_new_production_methods': late_methods,
            'late_source_reviewed_branch_outcomes': late_branches,
            'late_stable_new_io_families': stable_late_families,
            'extend': bool(late_methods or late_branches or stable_late_families)}


def main():
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
        inflight = state.get('inflight')
        if inflight and (not state['pending'] or state['pending'][0]['plan'] != inflight['plan']):
            state['pending'].insert(0, {'plan': inflight['plan'], 'parent': 'recovered'})
        if not state.get('selector_frontier_complete'):
            healthy_candidates = candidate_io(events('healthy-01'))
            queued = {tuple(x) for x in state['queued']}
            for candidate in healthy_candidates:
                plan = (candidate,)
                if plan not in queued:
                    state['pending'].append({'plan': list(plan), 'parent': 'healthy-01'})
                    state['queued'].append(list(plan))
                    queued.add(plan)
            state['seen_pretarget_io'] = sorted(set(state['seen_pretarget_io']) | set(healthy_candidates))
            state['selector_frontier_complete'] = True
            save(state)
    else:
        healthy = events('healthy-01')
        state = {
            'schema_version': 1, 'budget': 80, 'max_faults': 8,
            'pending': [{'plan': [x], 'parent': 'healthy-01'}
                        for x in candidate_io(healthy)],
            'queued': [], 'trials': [], 'finished': False,
            'seen_pretarget_io': candidate_io(healthy),
            'healthy_target_guard_count': sum(x[1] == 'TARGET_GUARD' for x in healthy),
        }
        state['queued'] = [x['plan'] for x in state['pending']]
        save(state)
    while not state['finished']:
        index = len(state['trials']) + 1
        if index > state['budget']:
            signal = late_extension_signal(state) if state['budget'] == 80 else None
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
                                state['pending'].append({'plan': list(plan), 'parent': previous['run_id']})
                                state['queued'].append(list(plan))
                                queued.add(plan)
                save(state)
                continue
            state.update(finished=True, final_status='quality_complete',
                         stop_reason='80_trial_budget_complete_no_late_valid_new_method_or_stable_io_family'
                         if state['budget'] == 80 else '128_trial_budget_complete')
            save(state)
            break
        if not state['pending']:
            state.update(finished=True, final_status='quality_complete',
                         stop_reason='observed_pretarget_io_selector_frontier_exhausted')
            save(state)
            break
        item = state['pending'].pop(0)
        plan = item['plan']
        run_id = 'trial-{:03d}'.format(index)
        result_path = ROOT / run_id / 'run.json'
        # A completed run can be reprocessed after interruption without rerunning the JUnit.
        if result_path.exists():
            run_result = json.loads(result_path.read_text())
            assert run_result['plan'] == plan
        else:
            state['inflight'] = {'run_id': run_id, 'plan': plan}
            save(state)
            run_result = run(run_id, plan)
        trial = analyze(run_id, plan, run_result)
        previous_io = set(state['seen_pretarget_io'])
        state['seen_pretarget_io'] = sorted(previous_io | set(trial['candidate_pretarget_io']))
        trial['new_pretarget_io_count'] = len(set(trial['candidate_pretarget_io']) - previous_io)
        if trial['target_after_final_fault'] and len(plan) < state['max_faults']:
            queued = {tuple(x) for x in state['queued']}
            additions = []
            for candidate in trial['candidate_pretarget_io']:
                extended = tuple(plan + [candidate])
                if extended not in queued:
                    additions.append({'plan': list(extended), 'parent': run_id})
                    state['queued'].append(list(extended))
                    queued.add(extended)
            state['pending'] = additions + state['pending']
        state['trials'].append(trial)
        state.pop('inflight', None)
        with LEDGER.open('a') as output:
            output.write(json.dumps(trial, sort_keys=True) + '\n')
            output.flush()
            os.fsync(output.fileno())
        save(state)
        print('trial={} depth={} exit={} strict={} target_after={} coverage_gain={} new_io={} elapsed={:.3f}s'.format(
            index, len(plan), trial['junit_exit'], trial['strict_injection'],
            trial['target_after_final_fault'], trial['new_production_coverage_lines'],
            trial['new_pretarget_io_count'], trial['elapsed_seconds']), flush=True)


if __name__ == '__main__':
    main()
