#!/usr/bin/env python3
"""Audit strict same-target trials against original release-JAR coverage and I/O."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess

from build import CASE22, HERE, JAVA8, original_classpath
from coverage import production_classes
from fuzz import ROOT, SEEDS, family, load_events, point, relevant

ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
JAR_NAMES = {'solr-core-8.11.4.jar', 'solr-solrj-8.11.4.jar',
             'lucene-core-8.11.4.jar'}


def coverage_totals(exec_files: list[Path]) -> dict[str, int]:
    jars = sorted({entry for entry in original_classpath().split(':')
                   if Path(entry).name in JAR_NAMES})
    if len(jars) != len(JAR_NAMES):
        raise RuntimeError(f'original release jars missing: {jars}')
    cp = ':'.join((str(HERE / 'classes'), str(CASE22 / 'v5/lib/jacoco-core.jar'),
                   str(ASM_TREE), original_classpath()))
    output = subprocess.run([str(JAVA8 / 'java'), '-Xmx2g', '-cp', cp,
                             'research.solrleadership.CoverageUnion',
                             *(str(path) for path in exec_files), '--jars', *jars],
                            capture_output=True, text=True, check=True).stdout
    product = production_classes()
    methods = branches = 0
    for line in output.splitlines():
        mark, name, method_count, branch_count = line.split('\t')
        if mark == 'C' and name.split('$', 1)[0] in product:
            methods += int(method_count)
            branches += int(branch_count)
    return {'covered_production_methods': methods,
            'covered_production_branch_outcomes': branches,
            'original_release_jar_count': len(jars)}


def io_families(directory: Path) -> tuple[set[str], set[str]]:
    points = [point(event) for event in load_events(directory)
              if event['event'] == 'IO_OBSERVED' and relevant(point(event))]
    raw = {'|'.join((item['marker'], item['siteId'], item['sourceKey'],
                     item['resource'])) for item in points}
    return raw, {family(item) for item in points}


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    completed = state['completed']
    valid = [row for row in completed if row['strict_injection']
             and row['target_preserved'] and Path(row['jacoco']).is_file()
             and Path(row['jacoco']).stat().st_size]
    healthy_exec = [directory / 'jacoco.exec' for directory in SEEDS]
    stages = {}
    for cutoff in (0, 60, 70, 80):
        exec_files = healthy_exec + [Path(row['jacoco']) for row in valid
                                    if row['trial_number'] <= cutoff]
        stages[str(cutoff)] = coverage_totals(exec_files)
    healthy_raw = set()
    healthy_semantic = set()
    for directory in SEEDS:
        raw, semantic = io_families(directory)
        healthy_raw |= raw
        healthy_semantic |= semantic
    combined_raw = set(healthy_raw)
    combined_semantic = set(healthy_semantic)
    for row in valid:
        raw, semantic = io_families(Path(row['trace']).parent)
        combined_raw |= raw
        combined_semantic |= semantic
    start = stages['0']
    end = stages['80'] if len(completed) >= 80 else coverage_totals(
        healthy_exec + [Path(row['jacoco']) for row in valid])
    report = {
        'methodology': 'original_release_jar_jacoco_union_and_exact_zookeeper_io',
        'campaign_status': state['status'],
        'budget': state['budget'],
        'fault_trials': len(completed),
        'total_attempts': sum(row['attempts'] for row in completed),
        'strict_injections': sum(row['strict_injection'] for row in completed),
        'strict_same_target_after_fault_trials': len(valid),
        'strict_same_target_trial_numbers': [row['trial_number'] for row in valid],
        'strict_exact_target_throw_trials': sum(
            row['strict_injection'] and row['exact_target_throw_after_last_fault'] > 0
            for row in completed),
        'junit_passed_trials': sum(row['junit_gate'] == [1, 0, 0]
                                   and row['junit_exit'] == 0 for row in completed),
        'fault_depths': dict(Counter(str(row['planned_faults']) for row in completed)),
        'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in completed), 3),
        'healthy_coverage': start,
        'healthy_plus_valid_coverage': end,
        'new_production_methods': (end['covered_production_methods']
                                   - start['covered_production_methods']),
        'new_production_branch_outcomes': (
            end['covered_production_branch_outcomes']
            - start['covered_production_branch_outcomes']),
        'late_coverage_stages': stages,
        'healthy_raw_io_families': len(healthy_raw),
        'healthy_semantic_io_families': len(healthy_semantic),
        'valid_raw_io_family_gain': len(combined_raw - healthy_raw),
        'valid_semantic_io_family_gain': len(combined_semantic - healthy_semantic),
        'io_feedback_normalization_only': True,
        'excluded_runtime_woven_classes': [
            'DistributedZkUpdateProcessor', 'SolrZkClient'],
    }
    destination = ROOT / 'final-audit.json'
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: report[key] for key in (
        'fault_trials', 'strict_same_target_after_fault_trials',
        'strict_exact_target_throw_trials', 'new_production_methods',
        'new_production_branch_outcomes', 'valid_semantic_io_family_gain')},
        sort_keys=True))


if __name__ == '__main__':
    main()
