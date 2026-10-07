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
import subprocess

from actor_audit import actor, audit, events, selected_check
from build import CLASSES, HERE
from mirror import NODE2_LOCAL, mirror_run
from offload_console import offload
from offload_non_candidate_raw import offload as offload_non_candidate_raw
from run_native import RUN_ROOT, run

STATE = HERE / 'campaign-state.json'
LEDGER = HERE / 'trial-ledger.jsonl'
CALIBRATION = HERE / 'calibration.json'
STOP = False
MIN_FREE_BYTES = (10 * (1 << 30) if NODE2_LOCAL
                  else int(2.2 * (1 << 30)) + 16 * (1 << 20))


def java_processes() -> int:
    output = subprocess.check_output(['ps', '-eo', 'comm='], text=True)
    return sum(name.strip() == 'java' for name in output.splitlines())


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
    if target is None or target[0] <= after:
        return []
    target_actor = actor(target[3])
    return list(dict.fromkeys(selector(row) for row in rows
               if row[1] == 'IO' and len(row[3]) >= 3
               and after < row[0] < target[0]
               and actor(row[3]) == target_actor))


def candidate_rows(rows) -> list[tuple[int, str]]:
    target = selected_check(rows)
    if target is None:
        return []
    target_actor = actor(target[3])
    return [(row[0], selector(row)) for row in rows
            if row[1] == 'IO' and len(row[3]) >= 3
            and row[0] < target[0] and actor(row[3]) == target_actor]


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


def repair_feedback(state: dict, item: dict) -> None:
    """Try bounded ordered deletions of faults applied in an invalid run."""
    plan = item['plan']
    applied = item['applied']
    if (item['effective'] or item['needs_source_review'] or len(plan) < 2
            or applied != plan[:len(applied)]):
        return
    indices = list(range(len(applied) - 1, max(-1, len(applied) - 4), -1))
    wrong = ([i for i, actor_id in enumerate(item['applied_actor_ids'])
              if actor_id != item['target_actor_id']]
             if item['target_actor_id'] is not None else [])
    if wrong and wrong[0] not in indices:
        indices.insert(0, wrong[0])
    if not indices and len(applied) < len(plan):
        indices = [len(applied)]
    for index in indices:
        proposal = plan[:index] + plan[index + 1:]
        before = len(state['known_plans'])
        queue(state, proposal, item['run_id'])
        if len(state['known_plans']) > before:
            reason = ('first_unapplied_fault' if index >= len(applied)
                      else 'applied_fault_in_invalid_plan')
            state.setdefault('repair_feedback_receipts', []).append({
                'source_run_id': item['run_id'], 'removed_index': index,
                'removed_selector': plan[index], 'plan': proposal, 'reason': reason})


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
             'healthy_seed_selectors': seed,
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
        best_score = max(x.get('score', 0) for x in pending)
        scored = [i for i, x in enumerate(pending) if x.get('score', 0) == best_score]
        suite = [i for i in scored if ':SUITE@@' in pending[i]['plan'][0]]
        test = [i for i in scored if i not in suite]
        # At the 267/36 checkpoint, suite prefixes retained the selected guard
        # more often than the saturated deeper test prefixes. Alternate phases
        # while preserving every queued observed-I/O plan.
        pool = suite if state.get('suite_gap', 0) >= 1 and suite else (test or suite)
        phase = 'suite' if pool is suite else 'test'
        prefer_deep = state.get(phase + '_depth_gap', 0) >= 5
        yields: dict[str, list[int]] = {}
        for trial in state['trials']:
            count = yields.setdefault(trial['plan'][0], [0, 0])
            count[0] += int(trial['effective'])
            count[1] += 1
        def priority(i: int) -> tuple[int, float, int, int, int]:
            job = pending[i]
            successes, attempts = yields.get(job['plan'][0], [0, 0])
            # Smoothed observed eligibility keeps unseen prefixes in play.
            yield_score = (successes + 1) / (attempts + 2)
            # Across 42 target-retaining applied callback faults at the
            # 350/41 checkpoint, none used the selected manager's client.
            # Keep those plans queued, but try other same-actor candidates first.
            callback_plan = any('zkCallback-' in selector for selector in job['plan'])
            return (-int(callback_plan), yield_score,
                    (1 if prefer_deep else -1) * len(job['plan']),
                    int('/aliases.json:TEST' in job['plan'][-1]), -i)
        index = max(pool, key=lambda i:
                    priority(i))
    job = pending.pop(index)
    state['shallow_gap'] = 0 if len(job['plan']) == 1 else state['shallow_gap'] + 1
    state['suite_gap'] = (0 if ':SUITE@@' in job['plan'][0]
                          else state.get('suite_gap', 0) + 1)
    state['depth_gap'] = (0 if len(job['plan']) >= 4
                          else state.get('depth_gap', 0) + 1)
    phase = 'suite' if ':SUITE@@' in job['plan'][0] else 'test'
    state[phase + '_depth_gap'] = (0 if len(job['plan']) >= 4
                                   else state.get(phase + '_depth_gap', 0) + 1)
    job['run_id'] = 'trial-{:03d}'.format(state['next_trial'])
    state['next_trial'] += 1
    return job


def prune_unreachable_suite_suffixes(state: dict) -> None:
    """Skip suffix plans with an observed setup-aborting fault prefix.

    A standalone abort plus an observed longer abort witnesses the prefix.
    Planned faults after that prefix cannot apply once suite setup ended.
    """
    witnesses: dict[str, dict[str, str]] = {}
    for item in state['trials']:
        first = item['plan'][0]
        if (':SUITE@@' not in first or item['test_started_count'] != 0
                or item['applied'] != [first] or item['effective']):
            continue
        kind = 'standalone' if len(item['plan']) == 1 else 'suffix'
        witnesses.setdefault(first, {})[kind] = item['run_id']
    proven = {first: runs for first, runs in witnesses.items()
              if {'standalone', 'suffix'} <= runs.keys()
              and not any(item['effective'] for item in state['trials']
                          if item['plan'][0] == first)}
    standalone = {first: runs['standalone'] for first, runs in witnesses.items()
                  if 'standalone' in runs}
    proven_prefixes: dict[tuple[str, ...], dict[str, str]] = {}
    for item in state['trials']:
        applied = item['applied']
        if (len(applied) < 2 or item['test_started_count'] != 0
                or item['selected_target_sequence'] is not None
                or applied != item['plan'][:len(applied)]
                or applied[-1] not in standalone):
            continue
        proven_prefixes[tuple(applied)] = {
            'standalone': standalone[applied[-1]], 'prefix_trial': item['run_id']}
    if not proven and not proven_prefixes:
        return
    kept = []
    skipped = state.setdefault('pruned_plans', [])
    for job in state['pending']:
        first = job['plan'][0]
        if len(job['plan']) > 1 and first in proven:
            skipped.append({'plan': job['plan'], 'parent': job['parent'],
                            'reason': 'suite_setup_ended_after_first_fault',
                            'witnesses': proven[first]})
        else:
            prefix = next((p for p in sorted(proven_prefixes, key=len, reverse=True)
                           if len(job['plan']) > len(p)
                           and tuple(job['plan'][:len(p)]) == p), None)
            if prefix is None:
                kept.append(job)
            else:
                skipped.append({'plan': job['plan'], 'parent': job['parent'],
                                'prefix': list(prefix),
                                'reason': 'suite_setup_ended_after_observed_fault_prefix',
                                'witnesses': proven_prefixes[prefix]})
    if len(kept) != len(state['pending']):
        state['pending'] = kept
        atomic_json(STATE, state)


def late_signal(state: dict) -> dict:
    valid = [item for item in state['trials'] if item['effective']]
    first: dict[str, int] = {}
    observations: dict[str, int] = {}
    base_families = {item.rsplit('@@', 1)[0]
                     for item in state['healthy_seed_selectors']}
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
    else:
        repair_feedback(state, item)
    state['inflight'] = None
    atomic_json(STATE, state)
    sync_ledger(state)
    mirror_run(job['run_id'], prune_derived=True)
    offload(item)
    offload_non_candidate_raw(item)
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
    if state['schema_version'] < 4:
        seed = candidates(events(RUN_ROOT / 'healthy-v2-a/events.tsv'))
        seed += [item for item in candidates(events(RUN_ROOT / 'healthy-v2-b/events.tsv'))
                 if item not in seed]
        state['healthy_seed_selectors'] = seed
        for value in seed:
            queue(state, [value], 'healthy-v2')
        for item in state['trials']:
            expand_feedback(state, item)
        state['schema_version'] = 4
        atomic_json(STATE, state)
    if not state.get('repair_feedback_seeded'):
        for item in state['trials']:
            repair_feedback(state, item)
        state['repair_feedback_seeded'] = True
        atomic_json(STATE, state)
    sync_ledger(state)
    for item in state['trials']:
        mirror_run(item['run_id'], prune_derived=True)
        offload(item)
        offload_non_candidate_raw(item)
    assert not state['finished'] or state['effective'] >= state['budget']
    while not state['finished'] and not STOP:
        if state.get('awaiting_extension_review'):
            decision = state.get('extension_decision')
            if decision == 'extend':
                state['budget'] = 128
                state['max_faults'] = 10
                state['extension_applied'] = True
                state['awaiting_extension_review'] = False
                state.pop('pause_reason', None)
                for item in state['trials']:
                    if item['effective'] and item['fault_count'] == 8:
                        expand_feedback(state, item)
                atomic_json(STATE, state)
            elif decision == 'stop':
                state['finished'] = True
                state['stop_reason'] = '80_effective_trial_budget_complete_after_source_review'
                state['awaiting_extension_review'] = False
                atomic_json(STATE, state)
                break
            else:
                print('late extension signal awaits source review', flush=True)
                break
        free = shutil.disk_usage('/').free
        if free <= MIN_FREE_BYTES:
            state['pause_reason'] = ('node2_free_bytes_{}_below_10GiB_guard'.format(free)
                                     if NODE2_LOCAL else
                                     'node0_free_bytes_{}_below_2.2GiB_plus_16MiB_guard'.format(free))
            atomic_json(STATE, state)
            break
        if NODE2_LOCAL and java_processes() >= 5:
            state['pause_reason'] = 'node2_java_process_count_at_least_5'
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
                    state['awaiting_extension_review'] = True
                    state['pause_reason'] = 'late_extension_signal_needs_source_review'
                    atomic_json(STATE, state)
                    break
            state['finished'] = True
            state['stop_reason'] = '{}_effective_trial_budget_complete'.format(state['budget'])
            atomic_json(STATE, state)
            break
        if state['inflight'] is None:
            prune_unreachable_suite_suffixes(state)
        if not state['pending'] and state['inflight'] is None:
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
