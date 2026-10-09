#!/usr/bin/env python3
"""Publish terminal ZK13 actor-aware JUnit evidence and per-trial times."""

import csv
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

CASE = Path(__file__).resolve().parent
PIVOT = CASE.parents[2]
EVIDENCE = CASE / 'evidence'
AUDIT = EVIDENCE / 'terminal-audit.json'
ARCHIVE = EVIDENCE / 'raw-runs.tar.gz'
BUILD = EVIDENCE / 'build-receipt.json'
TABLE = EVIDENCE / 'trial-times.csv'
RESULT = PIVOT / 'cases/ZOOKEEPER-13/result.json'
HISTORICAL = RESULT.with_name('result.pre-actor-v2.json')
README = RESULT.with_name('README.md')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    audit = json.loads(AUDIT.read_text())
    build = json.loads(BUILD.read_text())
    if audit['status'] not in ('budget_complete', 'queue_exhausted', 'attempt_cap') or \
            audit['selected_attempts'] != len(audit['trials']) or \
            audit['agent_sha256'] != build['agent_sha256'] or \
            audit['original_source_commit'] != build['source_commit'] or \
            audit['original_source_commit'] != '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae':
        raise RuntimeError('terminal raw audit, source, or agent identity differs')
    if sum(x['selected_target_throws'] for x in audit['trials']) != \
            audit['selected_target_throw_events'] or \
            any(x['effective'] and not x['postfault_target'] for x in audit['trials']):
        raise RuntimeError('selected guard/expected exception audit differs')
    # A changed guard branch or missing expected throw must be reviewed and
    # replayed before an automatic none-bug terminal classification.
    with tarfile.open(ARCHIVE, 'r:gz') as source_archive:
        checkpoint_blob = source_archive.extractfile('v2-campaign.json').read()
    if hashlib.sha256(checkpoint_blob).hexdigest() != audit['checkpoint_sha256']:
        raise RuntimeError('archived checkpoint differs from independent raw audit')
    checkpoint = json.loads(checkpoint_blob)
    if any(x['needs_source_review'] for x in checkpoint['results']):
        raise RuntimeError('source-review candidate needs replay before finalization')
    old = json.loads(RESULT.read_text())
    if old['case_id'] != 'ZOOKEEPER-13' or old['status'] != 'actor_identity_recheck_pending':
        raise RuntimeError('historical result no longer pending actor recheck')
    if not HISTORICAL.exists():
        shutil.copy2(RESULT, HISTORICAL)
    source = next(x for x in json.loads((PIVOT / 'checklist102.json').read_text())['rows']
                  if x['case_id'] == 'ZOOKEEPER-13')
    fields = ('run_id', 'elapsed_seconds', 'fault_depth', 'exact', 'effective',
              'postfault_target', 'selected_target_throws', 'junit_exit',
              'new_coverage_lines', 'new_io_families', 'invalid_reason',
              'events_sha256', 'coverage_sha256', 'receipt_sha256')
    with TABLE.open('w', newline='') as output:
        writer = csv.DictWriter(output, fields)
        writer.writeheader()
        for row in audit['trials']:
            writer.writerow({**{key: row[key] for key in fields if key in row},
                             'fault_depth': len(row['plan'])})
    complete = audit['status'] == 'budget_complete' and \
        audit['effective'] >= audit['effective_budget']
    result = {
        'case_id': 'ZOOKEEPER-13', 'system': 'ZooKeeper 3.8.7',
        'status': 'quality_complete' if complete else 'inconclusive_budget_unmet',
        'quality_complete': complete, 'campaign_finished': True,
        'stop_reason': ('effective_budget_complete' if complete else
                        audit['status'] + '_before_effective_budget'),
        'campaign_budget': audit['effective_budget'], 'max_faults': audit['max_faults'],
        'budget_denominator': ('exact ordered actor-bound fault plan and selected '
                               'peer-1/first-global-session guard after last fault'),
        'cluster_test': 'org.apache.zookeeper.test.ReadOnlyModeTest#testGlobalSessionInRO',
        'cluster_nodes': 3, 'source_path': source['source_path'],
        'source_line': source['source_line'], 'function': source['function'],
        'check_code': source['check_code'],
        'original_source_commit': audit['original_source_commit'],
        'methodology': 'original_cluster_junit_actor_v2_asm_line_feedback',
        'graphchecker_or_skeleton_runtime_dependency': False,
        'actor_identity': ('actual ReadOnlyZooKeeperServer self/peer1, connection '
                           'server, first ClientCnxn receiver and raw global session'),
        'fault_model': 'ordered IOException at bound client/server socket I/O',
        'fault_trials': audit['selected_attempts'],
        'fully_applied_trials': audit['exact_fault_plans'],
        'strict_injections': audit['exact_fault_plans'],
        'target_after_fault': audit['effective'],
        'post_fault_target_reach_trials': audit['effective'],
        'selected_target_throw_events': audit['selected_target_throw_events'],
        'healthy_expected_target_throw': True,
        'healthy_guard_and_throw_count_per_seed': [10, 10],
        'coverage_gain': audit['effective_coverage_gain'],
        'io_family_gain': audit['effective_io_family_gain'],
        'coverage_feedback': 'ASM production source-line IDs in selected instrumented methods',
        'elapsed_seconds': round(audit['healthy_seconds'] + audit['trial_seconds'], 3),
        'healthy_elapsed_seconds': audit['healthy_seconds'],
        'trial_elapsed_seconds': audit['trial_seconds'],
        'elapsed_measurement': 'sum of two healthy and all completed original-JUnit JVM times',
        'bug_mark': 'none', 'new_bug': False, 'known_bug': False,
        'target_reached': True,
        'reason': ('Selected peer-1 read-only guard and its CloseRequestException '
                   'are healthy expected behavior. Every faulted verdict and '
                   'feedback increment was independently audited from raw actor '
                   'and session receipts; no changed target branch was observed.'),
        'conditional_extension': {'extended': audit['effective_budget'] == 128,
                                  'effective_target': audit['effective_budget']},
        'limitations': [
            'This result covers the original selected embedded-cluster JUnit, not all workloads.',
            'The injected family covers bound socket I/O; other file or protocol sites are outside it.',
            'ASM line feedback covers instrumented production methods rather than the full codebase.'
        ],
        'evidence': {
            'audit': '../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/terminal-audit.json',
            'audit_sha256': sha(AUDIT),
            'raw_archive': '../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/raw-runs.tar.gz',
            'raw_archive_sha256': sha(ARCHIVE),
            'build_receipt': '../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/build-receipt.json',
            'build_receipt_sha256': sha(BUILD),
            'trial_table': '../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/trial-times.csv',
            'trial_table_sha256': sha(TABLE),
            'historical_result': 'result.pre-actor-v2.json',
            'historical_result_sha256': sha(HISTORICAL),
        },
        'legacy_coarse_actor': old.get('legacy_coarse_actor'),
        'trial_results_scope': 'actor_v2_original_junit_peer1_first_global_session',
    }
    RESULT.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    old_readme = README.with_name('README.pre-actor-v2.md')
    if README.exists() and not old_readme.exists():
        shutil.copy2(README, old_readme)
    README.write_text(
        '# ZOOKEEPER-13 actor-aware original-JUnit result\n\n'
        f'The selected check is `{result["function"]}` in `{result["source_path"]}`. '
        'The original `ReadOnlyModeTest#testGlobalSessionInRO` starts an embedded '
        'quorum, binds the actual read-only peer 1, and reconnects the first raw '
        'global session. Its `CloseRequestException` is expected.\n\n'
        f'Two healthy runs and {result["fault_trials"]} fault JUnits took '
        f'{result["elapsed_seconds"]} summed JVM seconds. '
        f'{result["fully_applied_trials"]} plans were exact; '
        f'{result["target_after_fault"]} retained the selected guard after the '
        f'last fault. Budget: {result["campaign_budget"]} effective, '
        f'maximum {result["max_faults"]} faults. New production line IDs: '
        f'{result["coverage_gain"]}; normalized I/O families: '
        f'{result["io_family_gain"]}. Result: **{result["status"]}**, '
        'bug mark `none`.\n\n'
        'The [raw audit](../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/terminal-audit.json), '
        '[per-trial time table](../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/trial-times.csv), '
        'and [compressed original-JUnit receipts](../../zk-actor-v2/cases/ZOOKEEPER-13/evidence/raw-runs.tar.gz) '
        'preserve the selected actor, raw session, applied fault sequence, target '
        'check, coverage, and original JUnit outcome. The older global-ordinal '
        '[result](result.pre-actor-v2.json) remains historical coarse evidence.\n')
    print(json.dumps({'status': result['status'], 'fault_trials': result['fault_trials'],
                      'effective': result['target_after_fault'],
                      'elapsed_seconds': result['elapsed_seconds']}, sort_keys=True))


if __name__ == '__main__':
    main()
