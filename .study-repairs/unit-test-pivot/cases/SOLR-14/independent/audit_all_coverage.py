#!/usr/bin/env python3
"""Union original Solr/Lucene method and branch coverage across both fault models."""

from __future__ import annotations

import json
from pathlib import Path

from audit_campaign_coverage import totals
from build import HERE


def valid(state_path: Path) -> tuple[list[int], list[Path]]:
    state = json.loads(state_path.read_text())
    selected = [row for row in state['completed']
                if row['strict_injection'] and row['target_preserved']
                and Path(row['jacoco']).is_file() and Path(row['jacoco']).stat().st_size]
    return [row['trial_number'] for row in selected], [Path(row['jacoco']) for row in selected]


def gain(later: dict, earlier: dict) -> dict:
    return {
        'new_production_methods': later['covered_production_methods']
                                  - earlier['covered_production_methods'],
        'new_production_branch_outcomes': later['covered_production_branch_outcomes']
                                          - earlier['covered_production_branch_outcomes'],
    }


def main() -> None:
    main_ids, main_exec = valid(HERE / 'campaign/state.json')
    native_ids, native_exec = valid(HERE / 'native/campaign/state.json')
    healthy = [HERE / name / 'jacoco.exec' for name in ('healthy-06', 'healthy-07')]
    healthy += [HERE / 'native' / name / 'jacoco.exec'
                for name in ('healthy-01', 'healthy-02')]
    calibration = HERE / 'native/calibration/first-read/jacoco.exec'
    if not calibration.is_file():
        raise RuntimeError('native strict retry calibration missing')
    base = totals(healthy)
    v1 = totals(healthy + main_exec)
    both = totals(healthy + main_exec + [calibration] + native_exec)
    report = {
        'methodology': 'original_release_jar_jacoco_union',
        'original_junit_healthy_seed_count': len(healthy),
        'main_valid_trial_numbers': main_ids,
        'native_valid_trial_numbers': native_ids,
        'native_retry_calibration_count': 1,
        'healthy': base,
        'healthy_plus_v1': v1,
        'healthy_plus_v1_and_native': both,
        'v1_gain_over_healthy': gain(v1, base),
        'native_gain_over_v1': gain(both, v1),
        'combined_gain_over_healthy': gain(both, base),
    }
    path = HERE / 'native/campaign/production-coverage-audit.json'
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
