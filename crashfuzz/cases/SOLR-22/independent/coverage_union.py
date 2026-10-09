#!/usr/bin/env python3
"""Audit cumulative original Solr/Lucene method and branch coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from build import HERE, CASE, JAVA8, original_classpath
from coverage import ASM_TREE, production_classes


SOURCE = HERE / 'audit-src/research/solr22/CoverageUnion.java'
CLASSES = HERE / 'audit-classes'


def original_jars() -> list[str]:
    names = {'solr-core-8.11.4.jar', 'solr-solrj-8.11.4.jar',
             'lucene-core-8.11.4.jar'}
    return sorted({entry for entry in original_classpath().split(':')
                   if Path(entry).name in names})


def union(exec_files: list[Path]) -> dict:
    if not exec_files:
        raise ValueError('at least one JaCoCo execution is required')
    CLASSES.mkdir(exist_ok=True)
    jacoco = CASE / 'v5/lib/jacoco-core.jar'
    helper = CLASSES / 'research/solr22/CoverageUnion.class'
    if not helper.is_file() or helper.stat().st_mtime < SOURCE.stat().st_mtime:
        subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                        '-cp', str(jacoco), '-d', str(CLASSES), str(SOURCE)],
                       check=True, capture_output=True, text=True)
    jars = original_jars()
    command = [str(JAVA8 / 'java'), '-Xmx2g', '-cp',
               ':'.join((str(CLASSES), str(jacoco), str(ASM_TREE), original_classpath())),
               'research.solr22.CoverageUnion', str(len(jars)), *jars,
               *(str(path) for path in exec_files)]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    production = production_classes()
    methods: set[str] = set()
    branches_by_class: dict[str, int] = {}
    branches = total = classes = 0
    for line in result.stdout.splitlines():
        fields = line.split('\t')
        name = fields[1]
        if name.split('$', 1)[0] not in production:
            continue
        if fields[0] == 'B':
            branches += int(fields[2]); total += int(fields[3]); classes += 1
            branches_by_class[name] = int(fields[2])
        elif fields[0] == 'M':
            methods.add(name + '#' + fields[2])
    return {'production_methods_covered': len(methods),
            'production_branch_outcomes_covered': branches,
            'production_branch_outcomes_total': total,
            'production_classes_analyzed': classes,
            'method_ids': sorted(methods),
            'branches_by_class': branches_by_class}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, default=HERE / 'campaign')
    parser.add_argument('--upto', type=int)
    parser.add_argument('--valid-only', action='store_true',
                        help='include only strict trials with a post-fault target check')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    state = json.loads((args.campaign / 'state.json').read_text())
    selected_prefix = state['completed'][:args.upto]
    completed = ([row for row in selected_prefix if row['strict_injection']
                  and row['target_check_after_last_fault'] > 0]
                 if args.valid_only else selected_prefix)
    paths = [HERE / 'healthy-7/jacoco.exec', HERE / 'healthy-8/jacoco.exec']
    paths.extend(Path(row['jacoco']) for row in completed)
    result = union(paths)
    result.pop('method_ids')
    result.pop('branches_by_class')
    result['completed_trials'] = len(completed)
    result['selected_prefix'] = len(selected_prefix)
    result['valid_only'] = args.valid_only
    result['exec_files'] = len(paths)
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end='')


if __name__ == '__main__':
    main()
