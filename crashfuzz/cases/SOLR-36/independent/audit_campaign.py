#!/usr/bin/env python3
"""Recount each check's bounded campaign from original traces and release jars."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess

from build import CASE22, HERE, JAVA8, original_classpath
from coverage import production_classes
from fuzz import GUARDS, SEEDS, family, load_events, point, relevant


ROOT = HERE / 'campaign'
ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
JAR_NAMES = {'solr-core-8.11.4.jar', 'solr-solrj-8.11.4.jar',
             'lucene-core-8.11.4.jar'}


def coverage_totals(exec_files: list[Path]) -> dict[str, int]:
    jars = sorted({entry for entry in original_classpath().split(':')
                   if Path(entry).name in JAR_NAMES})
    if len(jars) != len(JAR_NAMES):
        raise RuntimeError(f'original release jars missing: {jars}')
    cp = ':'.join((str(HERE / 'classes'),
                   str(CASE22 / 'v5/lib/jacoco-core.jar'), str(ASM_TREE),
                   original_classpath()))
    output = subprocess.run([str(JAVA8 / 'java'), '-Xmx2g', '-cp', cp,
                             'research.solrsubshard.CoverageUnion',
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


def io_families(directory: Path) -> set[str]:
    return {family(point(event)) for event in load_events(directory)
            if event['event'] == 'IO_OBSERVED' and relevant(point(event))}


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    helper = HERE / 'src/research/solrsubshard/CoverageUnion.java'
    cp = ':'.join((str(CASE22 / 'v5/lib/jacoco-core.jar'),
                   str(ASM_TREE), original_classpath()))
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', cp, '-d', str(HERE / 'classes'), str(helper)],
                   capture_output=True, text=True, check=True)
    healthy_exec = [directory / 'jacoco.exec' for directory in SEEDS]
    healthy_coverage = coverage_totals(healthy_exec)
    healthy_io = set().union(*(io_families(directory) for directory in SEEDS))
    for case_id in ('SOLR-36', 'SOLR-37'):
        identity = json.loads((ROOT / f'identity-audit-{case_id}.json').read_text())
        if identity['fault_trials'] != len(state['completed']):
            raise RuntimeError(f'{case_id} identity audit is stale')
        valid_numbers = {item['trial_number'] for item in identity['trials']
                         if item['postfault_same_last_fault_child_or_collection_scope']}
        valid = [row for row in state['completed']
                 if row['trial_number'] in valid_numbers]
        injected_exec = [Path(row['jacoco']) for row in valid
                         if Path(row['jacoco']).is_file()
                         and Path(row['jacoco']).stat().st_size]
        combined_coverage = coverage_totals(healthy_exec + injected_exec)
        combined_io = set(healthy_io)
        guard_operands = Counter()
        identity_by_trial = {item['trial_number']: item for item in identity['trials']}
        for row in valid:
            events = load_events(Path(row['trace']).parent)
            combined_io |= {family(point(event)) for event in events
                            if event['event'] == 'IO_OBSERVED'
                            and relevant(point(event))}
            last_fault = max(event['seq'] for event in events
                             if event['event'] == 'IO_OBSERVED'
                             and event['applied'])
            affected_child = identity_by_trial[row['trial_number']][
                'expected_child_for_last_fault']
            for event in events:
                if (event['event'] == 'TARGET_CHECK'
                        and event['marker'] == GUARDS[case_id]
                        and event['seq'] > last_fault
                        and (event['sourceKey'] == affected_child
                             if affected_child else event['sourceKey'].startswith(
                                 'SOLR/SUBSHARD/collection1/shard1_'))):
                    guard_operands[event['detail']] += 1
        report = {
            'case_id': case_id,
            'methodology': 'original_release_jar_jacoco_union_and_exact_zookeeper_io',
            'campaign_status': state['status'],
            'budget': state['budget'],
            'fault_trials': len(state['completed']),
            'total_attempts': sum(row['attempts'] for row in state['completed']),
            'strict_injections': sum(row['strict_injection'] for row in state['completed']),
            'strict_post_target_trials': len(valid),
            'strict_post_target_any_child_trials': identity['strict_postfault_any_child'],
            'strict_post_target_trial_numbers': [row['trial_number'] for row in valid],
            'strict_exact_target_throw_trials': sum(
                row['strict_injection']
                and row['exact_target_throw_after_last_fault'][case_id] > 0
                for row in state['completed']),
            'strict_exact_target_throw_trial_numbers': [
                row['trial_number'] for row in state['completed']
                if row['strict_injection']
                and row['exact_target_throw_after_last_fault'][case_id] > 0],
            'unmatched_trial_numbers': [row['trial_number']
                                        for row in state['completed']
                                        if not row['strict_injection']],
            'postfault_guard_operand_counts_on_affected_child': dict(guard_operands),
            'fault_depths': dict(Counter(str(row['planned_faults'])
                                         for row in state['completed'])),
            'junit_gate_counts': dict(Counter(str(row['junit_gate'])
                                               for row in state['completed'])),
            'elapsed_seconds': round(sum(row['elapsed_seconds']
                                         for row in state['completed']), 3),
            'healthy_coverage': healthy_coverage,
            'healthy_plus_valid_coverage': combined_coverage,
            'new_production_methods': (
                combined_coverage['covered_production_methods']
                - healthy_coverage['covered_production_methods']),
            'new_production_branch_outcomes': (
                combined_coverage['covered_production_branch_outcomes']
                - healthy_coverage['covered_production_branch_outcomes']),
            'healthy_semantic_io_families': len(healthy_io),
            'healthy_plus_valid_semantic_io_families': len(combined_io),
            'new_semantic_io_families': len(combined_io - healthy_io),
            'excluded_runtime_woven_classes': [
                'DistributedZkUpdateProcessor', 'SolrZkClient'],
        }
        destination = ROOT / f'final-audit-{case_id}.json'
        destination.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(json.dumps({key: report[key] for key in ('case_id', 'fault_trials',
              'strict_post_target_trials', 'strict_exact_target_throw_trials',
              'new_production_methods', 'new_production_branch_outcomes',
              'new_semantic_io_families')}, sort_keys=True))


if __name__ == '__main__':
    main()
