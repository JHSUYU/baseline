#!/usr/bin/env python3
"""Finish at the exhausted observed RPC door, excluding an exact duplicate."""
import json
from campaign import HERE, RESULT, coverage, parse_run, save


def main():
    data = json.loads(RESULT.read_text())
    assert data['fault_trials'] == 65
    items = data['fault_trial_details']
    duplicate = next(x for x in items if x['id'] == 'r065')
    original = next(x for x in items if x['id'] == 'r53')
    assert duplicate['plan'] == original['plan']
    duplicate['classification'] = 'duplicate_attempt'
    duplicate['duplicate_of'] = 'r53'
    duplicate['counted_as_effective_trial'] = False
    data['duplicate_attempts'] = [duplicate]
    items.remove(duplicate)
    plan = '1:IOException,2:IOException,3:SocketTimeoutException,4:IOException,5:IOException'
    assert plan not in {x['plan'] for x in items}
    trial = parse_run('r066', plan, execute=False)
    assert trial['strict'] and trial['target_after_final_fault'] and trial['junit_passed']
    trial['production_coverage'] = coverage([HERE / 'r066.exec'])
    execs = [HERE / 'healthy_cov.exec'] + [HERE / ('r%02d.exec' % i) for i in range(1, 65)]
    before_union = coverage(execs)
    after_union = coverage(execs + [HERE / 'r066.exec'])
    assert 'error' not in before_union and 'error' not in after_union
    trial['new_production_branches_vs_prior_trials'] = max(0, after_union['total_branches'] - before_union['total_branches'])
    trial['production_branch_union'] = after_union['total_branches']
    trial['new_meta_rpc_hit_ordinals_vs_healthy'] = sorted(set(trial['observed_rpc_hit_ordinals']) - {1})
    trial['lost_target'] = False
    assert trial['new_production_branches_vs_prior_trials'] == 0
    items.append(trial)
    data['fault_trials'] = len(items)
    data['strict_injections'] = sum(x['strict'] for x in items)
    data['requested_fault_events'] = sum(x['requested_fault_events'] for x in items)
    data['matched_fault_events'] = sum(x['matched_fault_events'] for x in items)
    data['applied_fault_events'] = sum(x['applied_fault_events'] for x in items)
    data['target_after_fault'] = sum(x['target_after_final_fault'] for x in items)
    data['lost_target_trials'] = sum(x.get('lost_target', False) for x in items)
    data['coverage_gain'] = after_union['total_branches'] - data['healthy_coverage']['total_branches']
    data['fault_union_production_branches'] = after_union['total_branches']
    data['elapsed_seconds'] = round((data['healthy_elapsed_seconds'] or 0)
                                    + sum(x['elapsed_seconds'] or 0 for x in items), 2)
    data['excluded_attempt_elapsed_seconds'] = duplicate['elapsed_seconds']
    data['new_meta_rpc_hit_ordinals'] = sorted(set().union(
        *(set(x['new_meta_rpc_hit_ordinals_vs_healthy']) for x in items)))
    data['selected_throw_line_911_covered'] = any(
        x.get('production_coverage', {}).get('target_lines', {}).get('911', {}).get('instructions', 0) > 0
        for x in items)
    data['selected_target_exception_trials'] = sum(x['target_exception_observed'] and x['target_after_final_fault'] for x in items)
    data['bug_mark'] = 'none'
    data['status'] = 'quality_complete'
    data['campaign_finished'] = True
    data['unused_conditional_budget_trials'] = 128 - data['fault_trials']
    data['stop_reason'] = (
        'Near trial 64, six strict faults exhausted the original test\'s six RPC attempts and '
        'added one production retry branch, so the authorized 128 ceiling was opened. '
        'The additional distinct five-fault order r066 added no production coverage or new I/O family. '
        'The observed meta table-state Get door has been exercised with 1–6 faults and all four '
        'legal exception families; seven or eight requests cannot match under the original retry '
        'limit. Further queued orders reuse the same door and retry paths, so the effective '
        'candidate queue was exhausted before the 128 ceiling.')
    data['instrumentation_provenance'] = {
        'counted_runtime': 'Native JUnit Platform launcher, case-local ByteBuddy agent, JaCoCo',
        'graphchecker_jar_used': False,
        'prewoven_classes_used': False,
        'region_skeletons_or_static_scope_map_read': False,
        'static_aggregate_or_closure_run': False,
        'exploratory_runner_note': 'One early uncounted healthy2 setup run used GraphChecker JUnitMethodRunner; no counted trial used it.'}
    data['evidence'] = {
        'readme': 'README.md', 'runner': 'work/run.sh', 'agent_source': 'work/src/HBase02Agent.java',
        'native_junit_source': 'work/src/NativeJUnit.java', 'coverage_source': 'work/src/CoverageReport.java',
        'healthy_log': 'work/healthy_cov.log', 'healthy_exec': 'work/healthy_cov.exec',
        'trial_logs': 'work/r01.log through work/r64.log, plus work/r066.log',
        'trial_coverage': 'Matching .exec files', 'duplicate_log': 'work/r065.log',
        'checkpoint_repair': 'work/repair_checkpoint.py', 'finalizer': 'work/finalize.py'}
    save(data)
    assert data['fault_trials'] == 65 and data['target_after_fault'] == 61
    assert data['lost_target_trials'] == 4 and data['strict_injections'] == 65
    assert data['coverage_gain'] == 31 and not data['selected_throw_line_911_covered']


if __name__ == '__main__':
    main()
