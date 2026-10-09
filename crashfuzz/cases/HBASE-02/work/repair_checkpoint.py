#!/usr/bin/env python3
"""Correct exceptional exits and import the completed orphan r63 without replay."""
import json
from campaign import HERE, RESULT, save
from extend_campaign import initial_plans, publish_one


def main():
    data = json.loads(RESULT.read_text())
    assert data['fault_trials'] == 62, data['fault_trials']
    for item in data['fault_trial_details']:
        if item['id'] in ('r61', 'r62'):
            assert item['strict']
            assert all(exception != 'none' for _, exception in item['guard_outcomes'])
            item['target_after_final_fault'] = False
            item['lost_target'] = True
    data['target_after_fault'] = sum(x['target_after_final_fault'] for x in data['fault_trial_details'])
    data['lost_target_trials'] = sum(x.get('lost_target', False) for x in data['fault_trial_details'])
    save(data)
    combos = list(initial_plans())
    previous_execs = [HERE / 'healthy_cov.exec'] + [HERE / ('r%02d.exec' % i)
                                                   for i in range(1, 63)]
    prior_union = data['fault_union_production_branches']
    publish_one(data, 'r63', combos[63 - 49], previous_execs, prior_union, execute=False)
    assert data['fault_trials'] == 63
    assert data['target_after_fault'] == 60
    assert data['lost_target_trials'] == 3


if __name__ == '__main__':
    main()
