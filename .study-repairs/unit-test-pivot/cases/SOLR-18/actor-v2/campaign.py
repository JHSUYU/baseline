#!/usr/bin/env python3
"""Checkpointed same-client, observed-I/O fault campaign for original SOLR-18 JUnit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal

from actor_audit import actor, audit, events, selected_check
from build import CLASSES, HERE
from mirror import mirror_run
from run_native import RUN_ROOT, run

STATE = HERE / 'campaign-state.json'
LEDGER = HERE / 'trial-ledger.jsonl'
CALIBRATION = HERE / 'calibration.json'
STOP = False
MIN_FREE_BYTES = int(2.2 * (1 << 30)) + 16 * (1 << 20)


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def sync_ledger(state: dict) -> None:
    temp = LEDGER.with_suffix('.jsonl.tmp')
    temp.write_text(''.join(json.dumps(item, sort_keys=True) + '\n'
                            for item in state['trials']))
    os.replace(temp, LEDGER)


def covered(run_id: str, kind: str) -> set[str]:
    path = RUN_ROOT / run_id / ('covered_' + kind + '.txt')
    return set(path.read_text().splitlines()) if path.exists() else set()


def selector(row) -> str:
    return row[3][0] + '@@' + row[3][1]


def candidates(rows, after=0) -> list[str]:
    target = selected_check(rows)
    start = next((row[0] for row in rows if row[1] == 'TEST_STARTED'), None)
    if target is None or start is None or target[0] <= after:
        return []
    target_actor = actor(target[3])
    return list(dict.fromkeys(selector(row) for row in rows
               if row[1] == 'IO' and len(row[3]) >= 3
               and max(start, after) < row[0] < target[0]
               and actor(row[3]) == target_actor))


def candidate_rows(rows) -> list[tuple[int, str]]:
    target = selected_check(rows)
    start = next((row[0] for row in rows if row[1] == 'TEST_STARTED'), None)
    if target is None or start is None:
        return []
    target_actor = actor(target[3])
    return [(row[0], selector(row)) for row in rows
            if row[1] == 'IO' and len(row[3]) >= 3
            and start < row[0] < target[0] and actor(row[3]) == target_actor]


def sample_candidates(items: list[str]) -> list[str]:
    # Favor distinct paths and threads while retaining writes and near-target I/O.
    result, families = [], set()
    for item in items:
        family = item.rsplit('@@', 1)[0]
        if family not in families:
            result.append(item)
            families.add(family)
    for item in reversed(items):
        if item not in result:
            result.append(item)
    return result[:20]


def queue(state: dict, plan: list[str], parent: str, score: int = 0) -> None:
    key = '|||'.join(plan)
    if key not in state['known_plans']:
        state['known_plans'].append(key)
        state['pending'].append({'plan': plan, 'parent': parent, 'score': score})


def expand_feedback(state: dict, item: dict) -> None:
    if not item['effective'] or len(item['plan']) >= state['max_faults']:
        return
    rows = events(RUN_ROOT / item['run_id'] / 'events.tsv')
    applied_sequences = [row[0] for row in rows if row[1] == 'FAULT_APPLIED']
    observed = candidate_rows(rows)
    selected = set(sample_candidates([value for _, value in observed]))
    for sequence, value in observed:
        if value in item['plan'] or value not in selected:
            continue
        position = sum(fault < sequence for fault in applied_sequences)
        plan = item['plan'][:position] + [value] + item['plan'][position:]
        queue(state, plan, item['run_id'], item.get('new_campaign_coverage_score', 0))


def initial_state() -> dict:
    calibration = json.loads(CALIBRATION.read_text())
    assert calibration['source_junit_sha_equal']
    assert calibration['original_a']['exit_code'] == 0
    for seed in ('actor_seed_a', 'actor_seed_b'):
        meta = calibration[seed]
        assert meta['junit_exit'] == 0 and meta['junit_summary_present']
        assert meta['assumption_failure_count'] == 0
    junit = CLASSES / 'org/apache/solr/cloud/AliasIntegrationTest.class'
    assert hashlib.sha256(junit.read_bytes()).hexdigest() == calibration['junit_class_sha256']
    seed = candidates(events(RUN_ROOT / 'healthy-v2-a/events.tsv'))
    assert seed and all('/' in item for item in seed)
    # Include both healthy interleavings without charging either against the budget.
    seed += [item for item in candidates(events(RUN_ROOT / 'healthy-v2-b/events.tsv'))
             if item not in seed]
    state = {'schema_version': 2, 'budget': 80, 'max_faults': 8,
             'effective': 0, 'attempts': 0, 'next_trial': 1,
             'pending': [], 'known_plans': [], 'trials': [],
             'inflight': None, 'finished': False, 'extension_applied': False,
             'healthy_seed_selectors_after_test_start': seed,
             'original_junit_sha256': calibration['junit_class_sha256'],
             'baseline_probes': sorted(covered('healthy-v2-a', 'probes') |
                                       covered('healthy-v2-b', 'probes')),
             'baseline_methods': sorted(covered('healthy-v2-a', 'methods') |
                                        covered('healthy-v2-b', 'methods')),
             'baseline_lines': sorted(covered('healthy-v2-a', 'lines') |
                                      covered('healthy-v2-b', 'lines')),
             'shallow_gap': 0}
    # Start with test-body alias operations, then other same-client sites.
    seed.sort(key=lambda item: (0 if '/aliases.json:TEST' in item else 1,
                                0 if '.setData:' in item else 1, item))
    for item in seed:
        queue(state, [item], 'healthy-v2')
    atomic_json(STATE, state)
    return state


def analyze(job: dict, meta: dict, state: dict) -> dict:
    run_id, plan = job['run_id'], job['plan']
    assert meta.get('junit_class_sha256', state['original_junit_sha256']) == state['original_junit_sha256']
    assert meta['original_junit'] and not meta['classpath_has_graphchecker_or_skeleton_jar']
    rows = events(RUN_ROOT / run_id / 'events.tsv')
    report = audit(RUN_ROOT / run_id / 'events.tsv', plan)
    applied = [row for row in rows if row[1] == 'FAULT_APPLIED']
    matched = [row for row in rows if row[1] == 'FAULT_MATCHED']
    target = selected_check(rows)
    target_actor = actor(target[3]) if target else None
    post_io = candidates(rows, applied[-1][0]) if applied else []
    base_probes = set(state['baseline_probes'])
    base_methods = set(state['baseline_methods'])
    base_lines = set(state['baseline_lines'])
    new_probes = sorted(covered(run_id, 'probes') - base_probes)
    new_methods = sorted(covered(run_id, 'methods') - base_methods)
    new_lines = sorted(covered(run_id, 'lines') - base_lines)
    relevant_probes = [probe for probe in new_probes
                       if 'org/apache/solr/common/cloud/' in probe]
    selected_throw = report.get('selected_target_outcome') == 'TARGET_THROW'
    effective = bool(report['effective'] and meta['test_started_count'] == 1
                     and meta['assumption_failure_count'] == 0)
    return {'run_id': run_id, 'parent': job['parent'], 'plan': plan,
            'fault_count': len(plan), 'junit_exit': meta['junit_exit'],
            'junit_summary_present': meta['junit_summary_present'],
            'assumption_failure_count': meta['assumption_failure_count'],
            'test_started_count': meta['test_started_count'],
            'elapsed_seconds': meta['elapsed_seconds'],
            'original_junit_sha256': state['original_junit_sha256'],
            'matched': [selector(row) for row in matched],
            'applied': [selector(row) for row in applied],
            'applied_actor_ids': [actor(row[3]) for row in applied],
            'target_actor_id': target_actor,
            'selected_target_sequence': report.get('selected_target_sequence'),
            'selected_target_outcome': report.get('selected_target_outcome'),
            'selected_json_equal': report.get('target_json_equal'),
            'strict_ordered_injection': report.get('strict_ordered_faults', False),
            'all_faults_on_target_client': report.get('all_faults_on_target_client', False),
            'target_after_final_fault': report.get('target_after_final_fault', False),
            'effective': effective, 'selected_target_throw': selected_throw,
            'all_target_throw_count': sum(row[1] == 'TARGET_THROW' for row in rows),
            'new_production_probes_vs_healthy': new_probes,
            'new_production_methods_vs_healthy': new_methods,
            'new_production_lines_vs_healthy': new_lines,
            'new_relevant_probes_vs_healthy': relevant_probes,
            'candidate_pretarget_io': post_io if effective else [],
            'needs_source_review': bool(selected_throw or (effective and
                    (meta['junit_exit'] != 0 or report.get('target_json_equal') is not True))),
            'bug_mark': 'none'}


def choose_pending(state: dict) -> dict:
    pending = state['pending']
    shallow = next((i for i, x in enumerate(pending) if len(x['plan']) == 1), None)
    if shallow is not None and state['shallow_gap'] >= 2:
        index = shallow
    else:
        index = max(range(len(pending)), key=lambda i:
                    (pending[i].get('score', 0), len(pending[i]['plan']),
                     int('/aliases.json' in pending[i]['plan'][-1]), -i))
    job = pending.pop(index)
    state['shallow_gap'] = 0 if len(job['plan']) == 1 else state['shallow_gap'] + 1
    job['run_id'] = 'trial-{:03d}'.format(state['next_trial'])
    state['next_trial'] += 1
    return job


def late_signal(state: dict) -> dict:
    valid = [item for item in state['trials'] if item['effective']]
    first: dict[str, int] = {}
    observations: dict[str, int] = {}
    base_families = {item.rsplit('@@', 1)[0]
                     for item in state['healthy_seed_selectors_after_test_start']}
    prior_probes: set[str] = set()
    prior_methods: set[str] = set()
    new_probes, new_methods = [], []
    for index, item in enumerate(valid, 1):
        probes = set(item['new_production_probes_vs_healthy'])
        methods = set(item['new_production_methods_vs_healthy'])
        if index > 72:
            new_probes.extend({'effective_index': index, 'probe': p}
                              for p in sorted(probes - prior_probes)
                              if p.startswith('org/apache/solr/common/cloud/'))
            new_methods.extend({'effective_index': index, 'method': m}
                               for m in sorted(methods - prior_methods)
                               if m.startswith('org/apache/solr/common/cloud/'))
        prior_probes |= probes
        prior_methods |= methods
        for family in {x.rsplit('@@', 1)[0] for x in item['candidate_pretarget_io']}:
            if family not in base_families and family not in first:
                first[family] = index
            if family in first:
                observations[family] = observations.get(family, 0) + 1
    stable = [{'family': key, 'first_effective_index': first[key],
               'effective_observations': observations[key]}
              for key in sorted(first) if first[key] > 72 and observations[key] >= 2]
    return {'last_eight_new_relevant_probes': new_probes,
            'last_eight_new_relevant_methods': new_methods,
            'last_eight_stable_relevant_io_families': stable,
            'extend': bool(new_probes or new_methods or stable)}


def record(state: dict, job: dict, meta: dict) -> dict:
    item = analyze(job, meta, state)
    seen_probes = {p for old in state['trials'] if old['effective']
                   for p in old['new_production_probes_vs_healthy']}
    seen_methods = {m for old in state['trials'] if old['effective']
                    for m in old['new_production_methods_vs_healthy']}
    novelty = len(set(item['new_production_probes_vs_healthy']) - seen_probes)
    novelty += 10 * len(set(item['new_production_methods_vs_healthy']) - seen_methods)
    item['new_campaign_coverage_score'] = novelty if item['effective'] else 0
    state['trials'].append(item)
    state['attempts'] += 1
    state['effective'] += int(item['effective'])
    if item['effective']:
        expand_feedback(state, item)
    state['inflight'] = None
    atomic_json(STATE, state)
    sync_ledger(state)
    mirror_run(job['run_id'], prune_derived=True)
    print('trial={} depth={} effective={}/{} strict={} same_client={} post={} '
          'exit={} outcome={} probes+={} methods+={} elapsed={:.3f}s'.format(
              job['run_id'], len(job['plan']), state['effective'], state['attempts'],
              item['strict_ordered_injection'], item['all_faults_on_target_client'],
              item['target_after_final_fault'], item['junit_exit'],
              item['selected_target_outcome'],
              len(item['new_production_probes_vs_healthy']),
              len(item['new_production_methods_vs_healthy']),
              item['elapsed_seconds']), flush=True)
    return item


def stop_requested(signum, frame):
    global STOP
    STOP = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pilot-effective', type=int, default=0)
    args = parser.parse_args()
    signal.signal(signal.SIGUSR1, stop_requested)
    state = json.loads(STATE.read_text()) if STATE.exists() else initial_state()
    if state['schema_version'] < 3:
        state['schema_version'] = 3
        for item in state['trials']:
            expand_feedback(state, item)
        atomic_json(STATE, state)
    sync_ledger(state)
    for item in state['trials']:
        mirror_run(item['run_id'], prune_derived=True)
    assert not state['finished'] or state['effective'] >= state['budget']
    while not state['finished'] and not STOP:
        free = shutil.disk_usage('/').free
        if free <= MIN_FREE_BYTES:
            state['pause_reason'] = 'node0_free_bytes_{}_below_2.2GiB_plus_16MiB_guard'.format(free)
            atomic_json(STATE, state)
            break
        state.pop('pause_reason', None)
        if args.pilot_effective and state['effective'] >= args.pilot_effective:
            break
        if state['effective'] >= state['budget']:
            if state['budget'] == 80:
                signal_ = late_signal(state)
                state['late_extension_signal'] = signal_
                if signal_['extend']:
                    state['budget'] = 128
                    state['max_faults'] = 10
                    state['extension_applied'] = True
                    for item in state['trials']:
                        if item['effective'] and item['fault_count'] == 8:
                            expand_feedback(state, item)
                    atomic_json(STATE, state)
                    continue
            state['finished'] = True
            state['stop_reason'] = '{}_effective_trial_budget_complete'.format(state['budget'])
            atomic_json(STATE, state)
            break
        if not state['pending']:
            state['finished'] = True
            state['stop_reason'] = 'observed_io_frontier_exhausted'
            atomic_json(STATE, state)
            break
        job = state['inflight'] or choose_pending(state)
        state['inflight'] = job
        atomic_json(STATE, state)
        path = RUN_ROOT / job['run_id'] / 'run.json'
        if path.exists():
            meta = json.loads(path.read_text())
            assert meta['plan'] == job['plan']
        else:
            meta = run(job['run_id'], job['plan'], timeout=300)
        item = record(state, job, meta)
        if item['needs_source_review']:
            print('source review required at ' + job['run_id'], flush=True)
    print(json.dumps({'attempts': state['attempts'], 'effective': state['effective'],
                      'budget': state['budget'], 'finished': state['finished'],
                      'stop_reason': state.get('stop_reason'),
                      'pending': len(state['pending'])}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
