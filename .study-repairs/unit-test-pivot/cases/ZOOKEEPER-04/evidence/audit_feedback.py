#!/usr/bin/env python3
"""Count observed target-preserving I/O occurrence candidates without graphs."""

import json
from pathlib import Path

import campaign


HERE = Path(__file__).resolve().parent
RUNS = Path('/users/ZhenyuLi/zk04-runs')


def main():
    summary = json.loads(campaign.SUMMARY.read_text())
    trials = summary['trials']
    traces = [campaign.SEED] + [RUNS / row['id'] for row in trials]
    potential = {}
    prior_fault_counts = {}
    observed = {}
    for run in traces:
        events = campaign.parse_events(run / 'events.tsv')
        guards = [e['seq'] for e in events if e['kind'] == 'TARGET_GUARD']
        for e in events:
            if e['kind'] != 'IO' or len(e['detail']) < 2:
                continue
            key = e['detail'][0] + '@@' + e['detail'][1]
            observed.setdefault(key, []).append(run.name)
            if any(seq > e['seq'] for seq in guards):
                potential.setdefault(key, []).append(run.name)
                before = sum(row['kind'] == 'FAULT_APPLIED' and row['seq'] < e['seq']
                             for row in events)
                prior_fault_counts.setdefault(key, []).append(before)
    exact_attempted = set()
    for row in trials:
        run_events = campaign.parse_events(RUNS / row['id'] / 'events.tsv')
        for e in run_events:
            if e['kind'] == 'FAULT_APPLIED' and len(e['detail']) >= 2:
                exact_attempted.add(e['detail'][0] + '@@' + e['detail'][1])
    untried = sorted(set(potential) - exact_attempted)
    budget_feasible_untried = [key for key in untried
                               if min(prior_fault_counts[key]) < 4]
    late_only = sorted(set(observed) - set(potential))
    target_preserving = [row['id'] for row in trials
                         if row['strict'] and row['target_after_fault']]
    union_cov = set()
    admitted_cov = set()
    for row in trials:
        union_cov.update(row['new_coverage_items'])
        if row['strict'] and row['target_after_fault']:
            admitted_cov.update(row['new_coverage_items'])
    output = {
        'methodology': 'direct runtime I/O site + global hit ordinal; no graph/static/aggregate/closure',
        'trace_count': len(traces),
        'trial_count': len(trials),
        'observed_distinct_io_occurrences': len(observed),
        'observed_pre_target_occurrences': len(potential),
        'exact_applied_occurrences': len(exact_attempted),
        'untried_observed_pre_target_occurrences': untried,
        'untried_with_fewer_than_four_prior_faults': budget_feasible_untried,
        'minimum_prior_applied_faults_for_untried_pretarget_occurrences': {
            key: min(prior_fault_counts[key]) for key in untried},
        'late_only_occurrences': late_only,
        'target_preserving_trial_ids': target_preserving,
        'target_preserving_trial_count': len(target_preserving),
        'observed_new_coverage_items': sorted(union_cov),
        'admitted_new_coverage_items': sorted(admitted_cov),
        'new_io_site_families': summary['union_new_io_sites_vs_seed'],
        'exact_target_throw_after_fault_trials': sum(
            row['target_throw_after_fault'] > 0 for row in trials),
        'scope_limit': 'Only bytecode-selected direct client TCP calls and QuorumPeer epoch open calls exposed by this original JUnit were eligible. This audit does not prove absence of uninstrumented I/O or every possible schedule.',
    }
    path = HERE / 'feedback-audit.json'
    path.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({k: v for k, v in output.items()
                      if k not in ('late_only_occurrences', 'observed_new_coverage_items',
                                   'admitted_new_coverage_items')}, indent=2))


if __name__ == '__main__':
    main()
