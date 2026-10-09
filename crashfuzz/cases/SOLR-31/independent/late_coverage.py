#!/usr/bin/env python3
"""Check whether original production coverage still grows near the 80-trial budget."""

from __future__ import annotations

import json
from pathlib import Path

from audit_campaign_coverage import ROOT, totals
from build import HERE


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    assert len(state['completed']) == 80
    valid = [row for row in state['completed']
             if row['strict_injection'] and row['target_preserved']
             and Path(row['jacoco']).is_file() and Path(row['jacoco']).stat().st_size]
    healthy = [HERE / name / 'jacoco.exec' for name in ('healthy-04', 'healthy-05')]
    stages = {}
    for cutoff in (0, 40, 60, 70, 80):
        paths = healthy + [Path(row['jacoco']) for row in valid
                           if row['trial_number'] <= cutoff]
        stages[str(cutoff)] = totals(paths)
    report = {
        'methodology': 'original_release_jar_jacoco_union',
        'stages': stages,
        'last_20_new_production_methods': (stages['80']['covered_production_methods']
                                            - stages['60']['covered_production_methods']),
        'last_20_new_production_branch_outcomes': (
            stages['80']['covered_production_branch_outcomes']
            - stages['60']['covered_production_branch_outcomes']),
        'last_10_new_production_methods': (stages['80']['covered_production_methods']
                                            - stages['70']['covered_production_methods']),
        'last_10_new_production_branch_outcomes': (
            stages['80']['covered_production_branch_outcomes']
            - stages['70']['covered_production_branch_outcomes']),
        'valid_trial_count': len(valid),
    }
    (ROOT / 'late-coverage-audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
