#!/usr/bin/env python3
"""Attribute trial 77's two late probes to exact original release-JAR classes."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from audit_campaign import JAR_NAMES, ROOT
from build import CASE22, HERE, JAVA8, original_classpath
from coverage import production_classes
from fuzz import SEEDS


SOURCE = HERE / 'src/research/solrsubshard/ProbeUnionAudit.java'
TRIAL_NUMBER = 77


def probes(exec_files: list[Path], jars: list[str]) -> set[tuple[str, str, int, bool]]:
    command = [str(JAVA8 / 'java'), '-Xmx2g', '-cp', ':'.join((
        str(HERE / 'classes'), str(CASE22 / 'v5/lib/jacoco-core.jar'))),
        'research.solrsubshard.ProbeUnionAudit',
        *(str(path) for path in exec_files), '--jars', *jars]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    product = production_classes()
    rows = set()
    for line in result.stdout.splitlines():
        mark, class_id, name, index, release_match = line.split('\t')
        if mark == 'P' and name.split('$', 1)[0] in product:
            rows.add((class_id, name, int(index), release_match == 'true'))
    return rows


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    completed = state['completed']
    if len(completed) < 80 or state['status'] != 'budget_complete':
        raise RuntimeError('audit requires the completed 80-trial checkpoint')
    target = completed[TRIAL_NUMBER - 1]
    if target['trial_number'] != TRIAL_NUMBER or not target['strict_injection']:
        raise RuntimeError('trial 77 is not an exact injected trial')
    identities = {}
    for case_id in ('SOLR-36', 'SOLR-37'):
        report = json.loads((ROOT / f'identity-audit-{case_id}.json').read_text())
        row = report['trials'][TRIAL_NUMBER - 1]
        if row['trial_number'] != TRIAL_NUMBER:
            raise RuntimeError(f'{case_id}: stale identity audit')
        identities[case_id] = row['postfault_same_last_fault_child_or_collection_scope']
    jars = sorted({entry for entry in original_classpath().split(':')
                   if Path(entry).name in JAR_NAMES})
    if len(jars) != len(JAR_NAMES):
        raise RuntimeError('original Solr/Lucene release JARs missing')
    cp = ':'.join((str(CASE22 / 'v5/lib/jacoco-core.jar'),
                   original_classpath()))
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', cp, '-d', str(HERE / 'classes'), str(SOURCE)],
                   capture_output=True, text=True, check=True)
    before_files = [directory / 'jacoco.exec' for directory in SEEDS]
    before_files += [Path(row['jacoco']) for row in completed[:TRIAL_NUMBER - 1]
                     if row['target_preserved'] and Path(row['jacoco']).is_file()]
    before = probes(before_files, jars)
    after = probes([Path(target['jacoco'])], jars)
    gained = sorted(after - before)
    if len(gained) != target['new_production_probes']:
        raise RuntimeError('offline probe delta differs from frozen scheduler')
    report = {
        'trial_number': TRIAL_NUMBER,
        'last_eight_window': [73, 80],
        'methodology': 'JaCoCo_probe_union_exact_original_release_jar_CRC64',
        'strict_injection': target['strict_injection'],
        'same_child_post_fault_target': identities,
        'original_junit_gate': target['junit_gate'],
        'reported_new_production_probes': target['new_production_probes'],
        'offline_new_production_probes': len(gained),
        'probes': [{'class_id': class_id, 'class_name': name,
                    'probe_index': index, 'original_release_jar_id_match': match}
                   for class_id, name, index, match in gained],
        'design_extension_gate_met': (
            bool(gained) and all(row[3] for row in gained)
            and all(identities.values()) and target['junit_gate'] == [1, 0, 0]),
    }
    destination = ROOT / 'trial-77-probe-audit.json'
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
