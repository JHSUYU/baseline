#!/usr/bin/env python3
"""Audit 80-to-128 extension against the cumulative effective-run union."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from audit_campaign import coverage_totals, rpc_families
from fuzz_rpc import CHECKS, SEEDS

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'campaign'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(state: dict) -> dict:
    if state['status'] != 'budget_complete' or state['active'] is not None:
        raise RuntimeError('late novelty audit requires a complete 80-stage boundary')
    if state['budget']['max_faults'] != 8:
        raise RuntimeError('late novelty audit expects max8 stage')
    healthy = [directory / 'jacoco.exec' for directory in SEEDS]
    healthy_families = set().union(*(rpc_families(directory) for directory in SEEDS))
    cases = {}
    for case_id in CHECKS:
        valid = [row for row in state['completed'] if row['strict_injection']
                 and row['postfault_same_child_guards'][case_id] > 0]
        if len(valid) < 8:
            raise RuntimeError(f'{case_id}: fewer than eight effective runs')
        earlier, late = valid[:-8], valid[-8:]
        before_exec = healthy + [Path(row['jacoco']) for row in earlier]
        after_exec = before_exec + [Path(row['jacoco']) for row in late]
        before_coverage = coverage_totals(before_exec)
        after_coverage = coverage_totals(after_exec)
        before_families = set(healthy_families)
        for row in earlier:
            before_families.update(rpc_families(Path(row['trace']).parent))
        late_families = set()
        for row in late:
            late_families.update(rpc_families(Path(row['trace']).parent))
        methods = (after_coverage['covered_production_methods'] -
                   before_coverage['covered_production_methods'])
        branches = (after_coverage['covered_production_branch_outcomes'] -
                    before_coverage['covered_production_branch_outcomes'])
        new_families = sorted(late_families - before_families)
        if methods < 0 or branches < 0:
            raise RuntimeError(f'{case_id}: coverage union shrank')
        cases[case_id] = {
            'effective_before_window': len(earlier),
            'last_eight_effective_trial_numbers': [row['trial_number'] for row in late],
            'last_eight_trace_sha256': {str(row['trial_number']): sha(Path(row['trace']))
                                        for row in late},
            'before_covered_production_methods': before_coverage['covered_production_methods'],
            'after_covered_production_methods': after_coverage['covered_production_methods'],
            'new_production_methods': methods,
            'before_covered_production_branch_outcomes':
                before_coverage['covered_production_branch_outcomes'],
            'after_covered_production_branch_outcomes':
                after_coverage['covered_production_branch_outcomes'],
            'new_production_branch_outcomes': branches,
            'new_relevant_http_io_families': len(new_families),
            'new_relevant_http_io_family_ids': new_families,
            'extend': bool(methods or branches or new_families),
        }
    return {
        'method': ('original release-JAR production method/branch union and sender-bound '
                   'HTTP I/O family union, each case last eight effective vs all earlier '
                   'effective runs plus healthy seeds'),
        'campaign_state_sha256': sha(ROOT / 'state.json'),
        'selected_plans': len(state['completed']),
        'cases': cases,
        'extend': any(item['extend'] for item in cases.values()),
    }


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    report = audit(state)
    path = ROOT / 'late-novelty-global-audit.json'
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)
    print(json.dumps({'selected_plans': report['selected_plans'],
                      'extend': report['extend'],
                      'cases': {case_id: {key: value for key, value in item.items()
                                          if key in ('new_production_methods',
                                                     'new_production_branch_outcomes',
                                                     'new_relevant_http_io_families', 'extend')}
                                for case_id, item in report['cases'].items()}}, sort_keys=True))


if __name__ == '__main__':
    main()
