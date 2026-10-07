#!/usr/bin/env python3
"""Audit sender-bound HTTP trials against original release-JAR coverage."""

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
from fuzz_rpc import SEEDS, point, rpc_events  # noqa: E402


ROOT = HERE / 'campaign'
JAR_NAMES = {'solr-core-8.11.4.jar', 'solr-solrj-8.11.4.jar',
             'lucene-core-8.11.4.jar'}
ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
RPC_CLASS = 'org/apache/solr/update/SolrCmdDistributor'
TARGET_CLASS = 'org/apache/solr/update/processor/DistributedZkUpdateProcessor'
ZK_CLASS = 'org/apache/solr/common/cloud/SolrZkClient'
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
    production = production_classes() - {RPC_CLASS, TARGET_CLASS, ZK_CLASS}
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
                      item['senderKey'], item['sourceKey'], item['resource']))
            for event in rpc_events(directory)
            for item in (point(event),)}


def main() -> None:
    stage2 = json.loads((ROOT / 'state.json').read_text())
    if stage2['status'] not in ('budget_complete', 'queue_exhausted',
                                'candidate_target_exception'):
        raise RuntimeError('RPC campaign is still active')
    stage_control = json.loads((ROOT / 'stage-status.json').read_text())
    if stage_control['status'] not in ('complete', 'queue_exhausted',
                                     'candidate', 'incomplete_budget_limit'):
        raise RuntimeError('HTTP stage driver has not reached a reviewable checkpoint')
    healthy = [directory / 'jacoco.exec' for directory in SEEDS]
    healthy_coverage = coverage_totals(healthy)
    healthy_rpc = set().union(*(rpc_families(directory)
                               for directory in SEEDS))
    legacy = json.loads((PARENT / 'campaign/final-audit-SOLR-36.json').read_text())
    source_seed = json.loads((HERE / 'seed-audit.json').read_text())
    agent_sha = source_seed['runs'][0]['agent_sha256']
    if any(run['agent_sha256'] != agent_sha for run in source_seed['runs']):
        raise RuntimeError('HTTP healthy seeds used different agents')
    for case_id in ('SOLR-36', 'SOLR-37'):
        valid2 = [row for row in stage2['completed']
                  if row['strict_injection']
                  and row['postfault_same_child_guards'][case_id] > 0]
        executions2 = [Path(row['jacoco']) for row in valid2]
        http_coverage = coverage_totals(healthy + executions2)
        observed_rpc = set(healthy_rpc)
        operands = Counter()
        for row in valid2:
            observed_rpc |= rpc_families(Path(row['trace']).parent)
            operands.update(row['postfault_guard_operands'][case_id])
        report = {
            'case_id': case_id,
            'methodology': 'sender_and_child_bound_http_original_junit_release_jar',
            'excluded_runtime_woven_classes': [
                'DistributedZkUpdateProcessor', 'SolrZkClient',
                'SolrCmdDistributor'],
            'legacy_zk_coarse_selected_plans': legacy['fault_trials'],
            'legacy_zk_coarse_actor_binding': 'unverified',
            'healthy_sender_child_seed_sha256': [
                run['trace_sha256'] for run in source_seed['runs']],
            'sender_bound_agent_sha256': agent_sha,
            'http_stage_control': stage_control,
            'stage2_http_status': stage2['status'],
            'stage2_http_budget': stage2['budget'],
            'stage2_http_selected_plans': len(stage2['completed']),
            'stage2_http_total_attempts': sum(row['attempts']
                                              for row in stage2['completed']),
            'stage2_http_strict_injections': sum(row['strict_injection']
                                                 for row in stage2['completed']),
            'stage2_http_effective_posttarget_same_child': len(valid2),
            'stage2_http_exact_target_throw_trials': sum(
                row['strict_injection']
                and row['postfault_same_child_throws'][case_id] > 0
                for row in stage2['completed']),
            'stage2_http_exact_target_throw_trial_numbers': [
                row['trial_number'] for row in stage2['completed']
                if row['strict_injection']
                and row['postfault_same_child_throws'][case_id] > 0],
            'stage2_http_postfault_guard_operands': dict(operands),
            'stage2_http_junit_gate_counts': dict(Counter(
                str(row['junit_gate']) for row in stage2['completed'])),
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
            'healthy_plus_effective_http_coverage': http_coverage,
            'http_additional_production_methods':
                http_coverage['covered_production_methods']
                - healthy_coverage['covered_production_methods'],
            'http_additional_production_branch_outcomes':
                http_coverage['covered_production_branch_outcomes']
                - healthy_coverage['covered_production_branch_outcomes'],
            'healthy_http_semantic_io_families': len(healthy_rpc),
            'healthy_plus_valid_http_semantic_io_families': len(observed_rpc),
            'new_http_semantic_io_families': len(observed_rpc - healthy_rpc),
        }
        path = ROOT / f'final-audit-{case_id}.json'
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(json.dumps({key: report[key] for key in
                          ('case_id', 'stage2_http_selected_plans',
                           'stage2_http_effective_posttarget_same_child',
                           'stage2_http_exact_target_throw_trials',
                           'http_additional_production_methods',
                           'http_additional_production_branch_outcomes')},
                         sort_keys=True))


if __name__ == '__main__':
    main()
