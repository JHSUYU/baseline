#!/usr/bin/env python3
"""Audit both fault stages against original release JAR production coverage."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path.insert(0, str(PARENT))
from build import CASE22, JAVA8, original_classpath  # noqa: E402
from coverage import production_classes  # noqa: E402
from fuzz import load_events, point, point_id  # noqa: E402


ROOT = HERE / 'campaign'
JAR_NAMES = {'solr-core-8.11.4.jar', 'solr-solrj-8.11.4.jar',
             'lucene-core-8.11.4.jar'}
ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
RPC_CLASS = 'org/apache/solr/update/SolrCmdDistributor'
MARKERS = frozenset(('FAULT:HTTP:parentForwardAdd',
                     'FAULT:HTTP:parentForwardDeleteById'))


def coverage_totals(executions: list[Path]) -> dict[str, int]:
    jars = sorted({entry for entry in original_classpath().split(':')
                   if Path(entry).name in JAR_NAMES})
    if len(jars) != len(JAR_NAMES):
        raise RuntimeError(f'original release jars missing: {jars}')
    cp = ':'.join((str(PARENT / 'classes'),
                   str(CASE22 / 'v5/lib/jacoco-core.jar'), str(ASM_TREE),
                   original_classpath()))
    output = subprocess.run(
        [str(JAVA8 / 'java'), '-Xmx2g', '-cp', cp,
         'research.solrsubshard.CoverageUnion',
         *(str(path) for path in executions), '--jars', *jars],
        capture_output=True, text=True, check=True).stdout
    production = production_classes() - {RPC_CLASS}
    methods = branches = 0
    for line in output.splitlines():
        mark, name, method_count, branch_count = line.split('\t')
        if mark == 'C' and name.split('$', 1)[0] in production:
            methods += int(method_count)
            branches += int(branch_count)
    return {'covered_production_methods': methods,
            'covered_production_branch_outcomes': branches,
            'original_release_jar_count': len(jars)}


def rpc_families(directory: Path) -> set[str]:
    return {'|'.join((item['marker'], item['siteId'],
                      item['sourceKey'], item['resource']))
            for event in load_events(directory)
            if event['event'] == 'IO_OBSERVED' and event['marker'] in MARKERS
            for item in (point(event),)}


def main() -> None:
    stage1 = json.loads((PARENT / 'campaign/state.json').read_text())
    stage2 = json.loads((ROOT / 'state.json').read_text())
    if stage2['status'] not in ('budget_complete', 'queue_exhausted',
                                'candidate_target_exception'):
        raise RuntimeError('RPC campaign is still active')
    healthy = [PARENT / 'healthy-02/jacoco.exec',
               PARENT / 'healthy-03/jacoco.exec',
               HERE / 'healthy-01/jacoco.exec',
               HERE / 'healthy-02/jacoco.exec']
    healthy_coverage = coverage_totals(healthy)
    healthy_rpc = set().union(*(rpc_families(directory)
                               for directory in (HERE / 'healthy-01',
                                                 HERE / 'healthy-02')))
    for case_id in ('SOLR-36', 'SOLR-37'):
        identity1 = json.loads((PARENT / f'campaign/identity-audit-{case_id}.json')
                               .read_text())
        if identity1['fault_trials'] != len(stage1['completed']):
            raise RuntimeError(f'{case_id}: stale stage1 identity')
        valid1_numbers = {item['trial_number'] for item in identity1['trials']
                          if item['postfault_same_last_fault_child_or_collection_scope']}
        valid1 = [row for row in stage1['completed']
                  if row['trial_number'] in valid1_numbers]
        valid2 = [row for row in stage2['completed']
                  if row['strict_injection']
                  and row['postfault_same_child_guards'][case_id] > 0]
        executions1 = [Path(row['jacoco']) for row in valid1]
        executions2 = [Path(row['jacoco']) for row in valid2]
        stage1_coverage = coverage_totals(healthy + executions1)
        combined_coverage = coverage_totals(healthy + executions1 + executions2)
        observed_rpc = set(healthy_rpc)
        for row in valid2:
            observed_rpc |= rpc_families(Path(row['trace']).parent)
        report = {
            'case_id': case_id,
            'methodology': 'original_release_jar_union_stage1_zk_plus_stage2_http',
            'excluded_runtime_woven_classes': [
                'DistributedZkUpdateProcessor', 'SolrZkClient',
                'SolrCmdDistributor'],
            'stage1_zk_fault_trials': len(stage1['completed']),
            'stage1_zk_strict_posttarget_same_child': len(valid1),
            'stage2_http_status': stage2['status'],
            'stage2_http_budget': stage2['budget'],
            'stage2_http_fault_trials': len(stage2['completed']),
            'stage2_http_total_attempts': sum(row['attempts']
                                              for row in stage2['completed']),
            'stage2_http_strict_injections': sum(row['strict_injection']
                                                 for row in stage2['completed']),
            'stage2_http_strict_posttarget_same_child': len(valid2),
            'stage2_http_exact_target_throw_trials': sum(
                row['strict_injection']
                and row['postfault_same_child_throws'][case_id] > 0
                for row in stage2['completed']),
            'stage2_http_elapsed_seconds': round(
                sum(row['elapsed_seconds'] for row in stage2['completed']), 3),
            'stage2_http_fault_depths': dict(Counter(
                str(row['planned_faults']) for row in stage2['completed'])),
            'stage2_http_fault_modes': dict(Counter(
                row['last_fault_mode'] for row in stage2['completed'])),
            'stage2_http_fault_command_families': dict(Counter(
                row['sequence'][-1]['point']['marker']
                for row in stage2['completed'])),
            'healthy_coverage': healthy_coverage,
            'healthy_plus_stage1_coverage': stage1_coverage,
            'healthy_plus_both_stages_coverage': combined_coverage,
            'stage2_additional_production_methods':
                combined_coverage['covered_production_methods']
                - stage1_coverage['covered_production_methods'],
            'stage2_additional_production_branch_outcomes':
                combined_coverage['covered_production_branch_outcomes']
                - stage1_coverage['covered_production_branch_outcomes'],
            'healthy_http_semantic_io_families': len(healthy_rpc),
            'healthy_plus_valid_http_semantic_io_families': len(observed_rpc),
            'new_http_semantic_io_families': len(observed_rpc - healthy_rpc),
        }
        path = ROOT / f'final-audit-{case_id}.json'
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(json.dumps({key: report[key] for key in
                          ('case_id', 'stage2_http_fault_trials',
                           'stage2_http_strict_posttarget_same_child',
                           'stage2_http_exact_target_throw_trials',
                           'stage2_additional_production_methods',
                           'stage2_additional_production_branch_outcomes')},
                         sort_keys=True))


if __name__ == '__main__':
    main()
