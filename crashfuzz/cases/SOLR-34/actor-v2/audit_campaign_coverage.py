#!/usr/bin/env python3
"""Audit production methods and branch outcomes using original release jars."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from build import CASE22, HERE, JAVA8, original_classpath
from coverage import ASM_TREE, JACOCO_CORE, production_classes


ROOT = HERE / 'campaign'
JAR_NAMES = {'solr-core-8.11.4.jar', 'solr-solrj-8.11.4.jar',
             'lucene-core-8.11.4.jar'}


def totals(paths: list[Path]) -> dict[str, int]:
    jars = sorted({entry for entry in original_classpath().split(':')
                   if Path(entry).name in JAR_NAMES})
    if len(jars) != len(JAR_NAMES):
        raise RuntimeError(f'original release jars missing: {jars}')
    helper = HERE / 'src/research/solrsplit/CoverageUnion.java'
    helper_class = HERE / 'classes/research/solrsplit/CoverageUnion.class'
    if not helper_class.is_file() or helper_class.stat().st_mtime < helper.stat().st_mtime:
        subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                        '-cp', str(JACOCO_CORE), '-d', str(HERE / 'classes'),
                        str(helper)], capture_output=True, text=True, check=True)
    cp = ':'.join((str(HERE / 'classes'), str(JACOCO_CORE), str(ASM_TREE),
                   original_classpath()))
    command = [str(JAVA8 / 'java'), '-Xmx2g', '-cp', cp,
               'research.solrsplit.CoverageUnion', *(str(path) for path in paths),
               '--jars', *jars]
    output = subprocess.run(command, text=True, capture_output=True, check=True).stdout
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


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    valid = [row for row in state['completed']
             if row['strict_injection'] and row['target_preserved']
             and Path(row['jacoco']).is_file() and Path(row['jacoco']).stat().st_size]
    healthy = [HERE / name / 'jacoco.exec' for name in ('healthy-01', 'healthy-02')]
    injected = [Path(row['jacoco']) for row in valid]
    base = totals(healthy)
    combined = totals(healthy + injected)
    report = {
        'methodology': 'original_release_jar_jacoco_union',
        'healthy': base,
        'strict_target_preserving_trial_numbers': [row['trial_number'] for row in valid],
        'valid_trial_count': len(valid),
        'healthy_plus_valid': combined,
        'new_production_methods': (combined['covered_production_methods']
                                   - base['covered_production_methods']),
        'new_production_branch_outcomes': (
            combined['covered_production_branch_outcomes']
            - base['covered_production_branch_outcomes']),
        'excluded_runtime_woven_classes': [
            'CoordinatorHttpSolrCall', 'SolrZkClient'],
    }
    path = ROOT / 'production-coverage-audit.json'
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
