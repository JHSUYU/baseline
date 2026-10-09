#!/usr/bin/env python3
"""Continue HBASE-02 from the 48-trial checkpoint under the revised budget."""
import itertools
import json
from pathlib import Path
import time

from campaign import HERE, KINDS, RESULT, coverage, parse_run, save


def initial_plans():
    # The four 4-fault orders omitted by campaign.py's first 48-plan matrix.
    for b in range(4):
        a = 3
        combo = (KINDS[a], KINDS[b], KINDS[(a + b) % 4], KINDS[(a + 2*b) % 4])
        yield combo
    # Eight 5-fault sequences exercise the sixth healthy RPC attempt.
    for a in range(4):
        yield tuple(KINDS[a] for _ in range(5))
        yield (KINDS[a], KINDS[(a + 1) % 4], KINDS[a], KINDS[(a + 1) % 4], KINDS[a])
    # Four 6-fault sequences probe the original test's retry limit.
    for a in range(4):
        yield tuple(KINDS[a] for _ in range(6))


def extended_plans():
    # All plans use <=6 because the original test permits only six RPC attempts.
    samples = list(itertools.product(KINDS, repeat=3))
    for i, (a, b, c) in enumerate(samples):
        if i < 32:
            yield (a, b, c, a, b)
        else:
            yield (a, b, c, a, b, c)


def plan_string(combo):
    return ','.join('%d:%s' % (n, kind) for n, kind in enumerate(combo, 1))


def publish_one(data, name, combo, previous_execs, prior_union, execute=True):
    item = parse_run(name, plan_string(combo), execute=execute)
    exe = HERE / (name + '.exec')
    if exe.exists():
        item['production_coverage'] = coverage([exe])
        union = coverage(previous_execs + [exe])
        item['new_production_branches_vs_prior_trials'] = max(0, union.get('total_branches', 0) - prior_union)
        item['production_branch_union'] = union.get('total_branches')
        prior_union = max(prior_union, union.get('total_branches', 0))
        previous_execs.append(exe)
    else:
        item['production_coverage'] = {'error': 'missing JaCoCo exec'}
        item['new_production_branches_vs_prior_trials'] = 0
    item['new_meta_rpc_hit_ordinals_vs_healthy'] = sorted(set(item['observed_rpc_hit_ordinals']) - {1})
    item['lost_target'] = item['strict'] and not item['target_after_final_fault']
    data['fault_trial_details'].append(item)
    items = data['fault_trial_details']
    data['fault_trials'] = len(items)
    data['strict_injections'] = sum(x['strict'] for x in items)
    data['requested_fault_events'] = sum(x['requested_fault_events'] for x in items)
    data['matched_fault_events'] = sum(x['matched_fault_events'] for x in items)
    data['applied_fault_events'] = sum(x['applied_fault_events'] for x in items)
    data['target_after_fault'] = sum(x['target_after_final_fault'] for x in items)
    data['lost_target_trials'] = sum(x.get('lost_target', False) for x in items)
    data['coverage_gain'] = max(0, prior_union - data['healthy_coverage']['total_branches'])
    data['fault_union_production_branches'] = prior_union
    data['elapsed_seconds'] = round((data['healthy_elapsed_seconds'] or 0)
                                    + sum(x['elapsed_seconds'] or 0 for x in items), 2)
    data['bug_mark'] = ('candidate_review' if any(x['target_exception_observed']
                         and x['target_after_final_fault'] for x in items) else 'none')
    data['new_io_marker_types'] = 0
    data['new_meta_rpc_hit_ordinals'] = sorted(set().union(
        *(set(x['new_meta_rpc_hit_ordinals_vs_healthy']) for x in items)))
    save(data)
    return prior_union


def main():
    while True:
        data = json.loads(RESULT.read_text())
        completed = data.get('fault_trials', 0)
        if (completed == 48 and data.get('campaign_finished')) or 49 <= completed < 64:
            break
        time.sleep(5)
    data['status'] = 'running'
    data['campaign_finished'] = False
    data['fault_budget'] = {'trials': 64, 'max_faults_per_trial': 6}
    save(data)
    previous_execs = [HERE / 'healthy_cov.exec'] + [HERE / ('r%02d.exec' % i)
                                                   for i in range(1, data['fault_trials'] + 1)]
    prior_union = data['fault_union_production_branches']
    for i, combo in enumerate(initial_plans(), 49):
        if i <= data['fault_trials']:
            continue
        prior_union = publish_one(data, 'r%02d' % i, combo, previous_execs, prior_union)
        if data['bug_mark'] == 'candidate_review':
            data['status'] = 'candidate_review'
            save(data)
            return
    recent = data['fault_trial_details'][-8:]
    fresh_near_limit = (any(x['new_production_branches_vs_prior_trials'] > 0 for x in recent)
                        or any(x.get('new_io_marker_types', 0) > 0 for x in recent))
    data['extension_decision'] = {
        'fresh_coverage_or_io_in_trials_57_to_64': fresh_near_limit,
        'recent_new_production_branches': sum(x['new_production_branches_vs_prior_trials'] for x in recent),
        'reason': 'Authorized conditional 128-trial extension' if fresh_near_limit
                  else 'No fresh production coverage or I/O family near trial 64'}
    if fresh_near_limit:
        data['fault_budget'] = {'trials': 128, 'max_faults_per_trial': 8,
                                'observed_rpc_attempt_limit': 6}
        save(data)
        for i, combo in enumerate(extended_plans(), 65):
            prior_union = publish_one(data, 'r%03d' % i, combo, previous_execs, prior_union)
            if data['bug_mark'] == 'candidate_review':
                data['status'] = 'candidate_review'
                save(data)
                return
    data['status'] = 'quality_complete'
    data['campaign_finished'] = True
    data['stop_reason'] = ('Completed the conditional 128-trial budget after new near-limit coverage'
                           if fresh_near_limit else 'Completed 64-trial budget; near-limit coverage plateau')
    save(data)


if __name__ == '__main__':
    main()
