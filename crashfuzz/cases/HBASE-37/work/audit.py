#!/usr/bin/env python3
"""Reparse every original JUnit execution and verify the campaign checkpoint."""
import json
from pathlib import Path
import re
import sys
from collections import Counter

import campaign
import supervisor

HERE = Path(__file__).resolve().parent
CASE = HERE.parent


def events(path):
    lines = path.read_text(errors='replace').splitlines()
    io, faults, reads, exits = [], [], [], []
    junit = None
    elapsed = None
    for n, line in enumerate(lines):
        m = re.search(r'HBASE37 IO seq=(\d+) selector=(\S+)', line)
        if m:
            io.append((n, int(m[1]), m[2]))
        m = re.search(r'HBASE37 FAULT_APPLIED seq=(\d+) step=(\d+) selector=(\S+) kind=(\S+)', line)
        if m:
            faults.append((n, int(m[1]), int(m[2]), m[3], m[4]))
        m = re.search(r'HBASE37 TARGET_READ call=(\d+) data_null=(true|false) path=(\S+)', line)
        if m:
            reads.append((n, int(m[1]), m[2] == 'true', m[3]))
        m = re.search(r'HBASE37 TARGET_EXIT call=(\d+) guard=(true|false) exact_exception=(true|false) thrown=(\S+)', line)
        if m:
            exits.append((n, int(m[1]), m[2] == 'true', m[3] == 'true', m[4]))
        m = re.search(r'HBASE37 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', line)
        if m:
            junit = {'found': int(m[1]), 'succeeded': int(m[2]), 'failed': int(m[3])}
        m = re.search(r'ELAPSED_SECONDS=([\d.]+)', line)
        if m:
            elapsed = float(m[1])
    if elapsed is None and path.name.startswith('r'):
        timing_path = HERE / 'timing-recovered.json'
        if timing_path.exists():
            elapsed = json.loads(timing_path.read_text()).get(path.stem, {}).get(
                'elapsed_seconds')
    return {'io': io, 'faults': faults, 'reads': reads, 'exits': exits,
            'junit': junit, 'elapsed_seconds': elapsed}


def eligible(trace, after=-1):
    stop = max((e[0] for e in trace['exits'] if e[2]), default=-1)
    return [x[2] for x in trace['io'] if after < x[0] < stop]


def site(selector):
    return '~'.join(selector.split('~')[:3])


def main():
    state = json.loads((HERE / 'checkpoint.json').read_text())
    trials = state['trials']
    seen = set(state['seen_plans'])
    errors = []
    all_sites, eligible_sites, target_lost_sites = set(), set(), set()
    depth, disposition, fault_kinds, applied_kinds = Counter(), Counter(), Counter(), Counter()
    exact_ids, direct_missing_ids, other_exact_ids = [], [], []
    junit_pass, junit_fail = 0, 0
    healthy = events(HERE / 'logs/healthy.log')
    roots = eligible(healthy)
    all_sites.update(site(x[2]) for x in healthy['io'])
    eligible_sites.update(site(x) for x in roots)
    for selector in roots:
        for kind in campaign.KINDS:
            if selector + '~' + kind not in seen:
                errors.append('missing healthy mutation: ' + selector + '~' + kind)

    for trial in trials:
        trace = events(CASE / trial['log'])
        plan = trial['plan']
        depth[len(plan)] += 1
        disposition[trial['disposition']] += 1
        fault_kinds.update(x.split('~')[-1] for x in plan)
        applied_kinds.update(x[4] for x in trace['faults'])
        all_sites.update(site(x[2]) for x in trace['io'])
        ordered = (len(trace['faults']) == len(plan) and all(
            f[2] == i and f[3] + '~' + f[4] == p
            for i, (f, p) in enumerate(zip(trace['faults'], plan), 1)))
        last = trace['faults'][-1][0] if trace['faults'] else -1
        post = [e for e in trace['exits'] if e[0] > last and e[2]] if ordered else []
        exact = [e for e in post if e[3]]
        if ordered != trial['strict'] or bool(post) != trial['target_after_fault'] \
                or bool(exact) != trial['exact_exception']:
            errors.append(trial['id'] + ': ordered or target outcome mismatch')
        if trace['junit'] != trial['junit'] or trace['elapsed_seconds'] != trial['elapsed_seconds']:
            errors.append(trial['id'] + ': JUnit or elapsed mismatch')
        if trace['junit'] == {'found': 1, 'succeeded': 1, 'failed': 0}:
            junit_pass += 1
        elif trace['junit'] is not None:
            junit_fail += 1
        read_ids = {r[1] for r in trace['reads']}
        if any(e[1] not in read_ids for e in trace['exits'] if e[2]):
            errors.append(trial['id'] + ': guard without completed ZK read')
        if exact:
            exact_ids.append(trial['id'])
            direct = any(f[4] == 'NONODE' and
                         'MasterAddressTracker.getMasterInfoPort:' in f[3]
                         for f in trace['faults'])
            if direct:
                direct_missing_ids.append(trial['id'])
            else:
                other_exact_ids.append(trial['id'])
        if trial['effective']:
            if len(plan) < state.get('depth_expanded_to', 8):
                selectors = eligible(trace, last)
                eligible_sites.update(site(x) for x in selectors)
                for selector in selectors:
                    for kind in campaign.KINDS:
                        generated = ';'.join(plan + [selector + '~' + kind])
                        if generated not in seen:
                            errors.append(trial['id'] + ': missing mutation ' + generated)
        else:
            target_lost_sites.update(site(x[2]) for x in trace['io'])

    if len({';'.join(t['plan']) for t in trials}) != len(trials):
        errors.append('duplicate completed exact fault plan')
    union = campaign.cov(state['coverage_execs'])
    if union != state['coverage_union']:
        errors.append('JaCoCo union differs from checkpoint')
    replay = events(HERE / 'logs/replay-r002.log')
    r002 = next((t for t in trials if t['id'] == 'r002'), None)
    if not r002 or len(replay['faults']) != len(r002['plan']) \
            or not any(e[2] and e[3] for e in replay['exits']):
        errors.append('r002 replay did not reproduce the exact target exception')
    admitted = [t for t in trials if t['effective']]
    summary = {
        'case_id': 'HBASE-37', 'attempts': len(trials),
        'effective_trials': len(admitted), 'strict_trials': sum(t['strict'] for t in trials),
        'post_fault_target_trials': sum(t['target_after_fault'] for t in trials),
        'unique_exact_plans': len({';'.join(t['plan']) for t in trials}),
        'requested_fault_events': sum(len(t['plan']) for t in trials),
        'applied_fault_events': sum(len(events(CASE / t['log'])['faults']) for t in trials),
        'requested_fault_kinds': dict(fault_kinds), 'applied_fault_kinds': dict(applied_kinds),
        'sequence_depths': dict(depth), 'dispositions': dict(disposition),
        'junit_passed_attempts': junit_pass, 'junit_other_outcomes': junit_fail,
        'exact_exception_trial_ids': exact_ids,
        'direct_injected_nonode_trial_ids': direct_missing_ids,
        'other_exact_exception_trial_ids': other_exact_ids,
        'healthy_pre_target_selectors': roots,
        'all_observed_io_sites': sorted(all_sites),
        'eligible_pre_target_sites': sorted(eligible_sites),
        'sites_observed_only_after_target_or_in_excluded_runs': sorted(all_sites - eligible_sites),
        'target_lost_trace_sites_excluded_from_feedback': sorted(target_lost_sites),
        'remaining_queue': len(state['queue']),
        'new_production_methods': union['methods'] - state['healthy_coverage']['methods'],
        'new_production_branches': union['branches'] - state['healthy_coverage']['branches'],
        'new_stable_io_sites': len({site(x) for x in state['observed_selectors']}
                                   - {site(x) for x in state['healthy_selectors']}),
        'last_16_effective_novelty': supervisor.late_novelty(state)
            if len(admitted) >= 16 else None,
        'cumulative_target_lines': union['target'],
        'elapsed_seconds_including_healthy': round(healthy['elapsed_seconds']
            + sum(t['elapsed_seconds'] or 0 for t in trials), 2),
        'errors': errors,
    }
    path = HERE / 'audit-summary.json'
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)
    print(json.dumps({k: v for k, v in summary.items() if k not in
                      ('all_observed_io_sites', 'eligible_pre_target_sites',
                       'target_lost_trace_sites_excluded_from_feedback',
                       'sites_observed_only_after_target_or_in_excluded_runs',
                       'healthy_pre_target_selectors')}, indent=2))
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
