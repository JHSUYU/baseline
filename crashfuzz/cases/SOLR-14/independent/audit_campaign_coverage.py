#!/usr/bin/env python3
"""Audit original production method/branch union for valid strict split trials."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from build import CASE22, HERE, JAVA8, original_classpath
from coverage import production_classes


ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
STATE = HERE / 'campaign/state.json'


def totals(paths: list[Path]) -> dict[str, int]:
    jars = sorted({entry for entry in original_classpath().split(':')
                   if Path(entry).name in {'solr-core-8.11.4.jar',
                                           'solr-solrj-8.11.4.jar',
                                           'lucene-core-8.11.4.jar'}})
    assert len(jars) == 3, jars
    cp = ':'.join((str(HERE / 'classes'), str(CASE22 / 'v5/lib/jacoco-core.jar'),
                   str(ASM_TREE), original_classpath()))
    command = [str(JAVA8 / 'java'), '-Xmx2g', '-cp', cp,
               'research.solrsplit.CoverageUnion', *(str(path) for path in paths),
               '--jars', *jars]
    output = subprocess.run(command, text=True, capture_output=True, check=True).stdout
    production = production_classes()
    methods = branches = 0
    for line in output.splitlines():
        mark, name, method_count, branch_count = line.split('\t')
        if mark == 'C' and name.split('$', 1)[0] in production:
            methods += int(method_count)
            branches += int(branch_count)
    return {'covered_production_methods': methods,
            'covered_production_branch_outcomes': branches,
            'original_release_jar_count': len(jars)}


def main() -> None:
    state = json.loads(STATE.read_text())
    valid = [row for row in state['completed']
             if row['strict_injection'] and row['target_preserved']
             and Path(row['jacoco']).is_file() and Path(row['jacoco']).stat().st_size]
    healthy = [HERE / name / 'jacoco.exec' for name in ('healthy-06', 'healthy-07')]
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
    }
    path = HERE / 'campaign/production-coverage-audit.json'
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
