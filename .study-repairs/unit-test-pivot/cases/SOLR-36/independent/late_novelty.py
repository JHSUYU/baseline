#!/usr/bin/env python3
"""Measure late campaign novelty using original release JAR coverage only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_campaign import ROOT, coverage_totals, io_families
from fuzz import SEEDS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--last-eight', action='store_true',
                        help='recount only the final eight-trial budget decision')
    args = parser.parse_args()
    state = json.loads((ROOT / 'state.json').read_text())
    completed = state['completed']
    if state['status'] not in ('budget_complete', 'queue_exhausted',
                               'candidate_target_exception'):
        raise RuntimeError('late novelty requires a terminal campaign')
    if not completed:
        raise RuntimeError('no completed trials')
    healthy_exec = [directory / 'jacoco.exec' for directory in SEEDS]
    healthy_io = set().union(*(io_families(directory) for directory in SEEDS))
    if args.last_eight:
        boundaries = [max(0, len(completed) - 8), len(completed)]
    else:
        boundaries = sorted({0, 20, 40, 60, 70,
                             max(0, len(completed) - 16),
                             max(0, len(completed) - 8),
                             len(completed)} &
                            set(range(len(completed) + 1)))
    for case_id in ('SOLR-36', 'SOLR-37'):
        identity = json.loads(
            (ROOT / f'identity-audit-{case_id}.json').read_text())
        if identity['fault_trials'] != len(completed):
            raise RuntimeError(f'{case_id}: stale identity audit')
        valid = {row['trial_number'] for row in identity['trials']
                 if row['postfault_same_last_fault_child_or_collection_scope']}
        stages = []
        for boundary in boundaries:
            selected = [row for row in completed[:boundary]
                        if row['trial_number'] in valid]
            exec_files = healthy_exec + [Path(row['jacoco']) for row in selected
                                         if Path(row['jacoco']).is_file()
                                         and Path(row['jacoco']).stat().st_size]
            coverage = coverage_totals(exec_files)
            io = set(healthy_io)
            for row in selected:
                io |= io_families(Path(row['trace']).parent)
            stages.append({
                'selected_trials_through': boundary,
                'strict_same_child_post_target_trials': len(selected),
                'covered_production_methods': coverage['covered_production_methods'],
                'covered_production_branch_outcomes':
                    coverage['covered_production_branch_outcomes'],
                'semantic_io_families': len(io),
                'distinct_first_fault_families':
                    len({row['first_family'] for row in completed[:boundary]}),
            })
        report = {
            'case_id': case_id,
            'source_campaign_status': state['status'],
            'source_completed_trials': len(completed),
            'methodology': 'cumulative_original_release_jar_union_same_child_posttarget',
            'stages': stages,
        }
        suffix = '-last-eight' if args.last_eight else ''
        destination = ROOT / f'late-novelty-{case_id}{suffix}.json'
        destination.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(json.dumps({'case_id': case_id, 'stages': stages}, sort_keys=True))


if __name__ == '__main__':
    main()
