#!/usr/bin/env python3
"""Audit original production coverage within the unchanged multi-node chaos JUnit."""

from __future__ import annotations

import json

from audit_campaign_coverage import totals
from build import HERE


ROOT = HERE / 'supplemental/shardsplit'


def gain(now: dict, before: dict) -> dict:
    return {
        'new_production_methods': now['covered_production_methods']
                                  - before['covered_production_methods'],
        'new_production_branch_outcomes': now['covered_production_branch_outcomes']
                                          - before['covered_production_branch_outcomes'],
    }


def main() -> None:
    healthy_names = ('native-chaos-02', 'native-chaos-03')
    fault_names = ('native-chaos-fault-01', 'native-chaos-fault-02')
    healthy = [ROOT / name / 'jacoco.exec' for name in healthy_names]
    faults = [ROOT / name / 'jacoco.exec' for name in fault_names]
    for file in healthy + faults:
        assert file.is_file() and file.stat().st_size, file
    base = totals(healthy)
    one = totals(healthy + faults[:1])
    both = totals(healthy + faults)
    result = {
        'methodology': 'original_release_jar_jacoco_union_same_original_cluster_test',
        'healthy_runs': list(healthy_names),
        'strict_fault_runs': list(fault_names),
        'healthy': base,
        'healthy_plus_one_fault_trial': one,
        'healthy_plus_two_fault_trials': both,
        'first_fault_trial_gain': gain(one, base),
        'second_fault_trial_increment': gain(both, one),
        'combined_fault_gain': gain(both, base),
        'exact_target_exception': 'SOLR-15 line538 only in second fault trial; source-reviewed expected protective abort',
    }
    out = ROOT / 'native-chaos-coverage-audit.json'
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
