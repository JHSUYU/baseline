#!/usr/bin/env python3
"""Publish ZK03's separately audited pre-I/O and complete-response stages."""

import csv
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

CASE = Path(__file__).resolve().parent
PIVOT = CASE.parents[3]
PRE = CASE.parent / 'evidence/pre-io-summary.json'
EVIDENCE = CASE / 'evidence'
AUDIT = EVIDENCE / 'terminal-audit.json'
ARCHIVE = EVIDENCE / 'raw-runs.tar.gz'
BUILD = EVIDENCE / 'build-receipt.json'
TABLE = EVIDENCE / 'trial-times.csv'
RESULT = PIVOT / 'cases/ZOOKEEPER-03/result.json'
HISTORICAL = RESULT.with_name('result.pre-actor-v2.json')
README = RESULT.with_name('README.md')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    pre = json.loads(PRE.read_text())
    post = json.loads(AUDIT.read_text())
    build = json.loads(BUILD.read_text())
    if pre['status'] != 'attempt_cap' or pre['effective'] != 37 or \
            pre['selected_attempts'] != 480 or pre['selected_target_throw_events'] or \
            post['status'] not in ('budget_complete', 'queue_exhausted', 'attempt_cap') or \
            post['selected_attempts'] != len(post['trials']) or \
            post['original_source_commit'] != pre['original_source_commit'] or \
            post['original_source_commit'] != build['source_commit'] or \
            post['agent_sha256'] != build['agent_sha256'] or \
            post['original_source_commit'] != '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae':
        raise RuntimeError('pre/post raw audit, original source, or agent differs')
    if post['selected_target_throw_events'] or \
            any(x['effective'] and not x['postfault_target'] for x in post['trials']):
        raise RuntimeError('target exception or strict actor receipt needs review')
    with tarfile.open(ARCHIVE, 'r:gz') as source_archive:
        checkpoint_blob = source_archive.extractfile('v2-campaign.json').read()
    if hashlib.sha256(checkpoint_blob).hexdigest() != post['checkpoint_sha256']:
        raise RuntimeError('archived checkpoint differs from independent audit')
    if any(x['needs_source_review'] for x in json.loads(checkpoint_blob)['results']):
        raise RuntimeError('source-review candidate needs replay before finalization')
    old = json.loads(RESULT.read_text())
    if old['case_id'] != 'ZOOKEEPER-03' or old['status'] != 'actor_identity_recheck_pending':
        raise RuntimeError('historical result no longer pending actor recheck')
    if not HISTORICAL.exists():
        shutil.copy2(RESULT, HISTORICAL)
    source = next(x for x in json.loads((PIVOT / 'checklist102.json').read_text())['rows']
                  if x['case_id'] == 'ZOOKEEPER-03')
    fields = ('run_id', 'elapsed_seconds', 'fault_depth', 'exact', 'effective',
              'postfault_target', 'selected_target_throws', 'junit_exit',
              'new_coverage_lines', 'new_io_families', 'invalid_reason',
              'events_sha256', 'coverage_sha256', 'receipt_sha256')
    with TABLE.open('w', newline='') as output:
        writer = csv.DictWriter(output, fields)
        writer.writeheader()
        for row in post['trials']:
            writer.writerow({**{key: row[key] for key in fields if key in row},
                             'fault_depth': len(row['plan'])})
    complete = post['status'] == 'budget_complete' and \
        post['effective'] >= post['effective_budget']
    total_fault_trials = pre['selected_attempts'] + post['selected_attempts']
    total_exact = pre['exact_fault_plans'] + post['exact_fault_plans']
    total_effective = pre['effective'] + post['effective']
    result = {
        'case_id': 'ZOOKEEPER-03', 'system': 'ZooKeeper 3.8.7',
        'status': 'quality_complete' if complete else 'inconclusive_budget_unmet',
        'quality_complete': complete, 'campaign_finished': True,
        'stop_reason': ('post_response_effective_budget_complete' if complete else
                        'post_response_' + post['status'] + '_before_effective_budget'),
        'campaign_budget': post['effective_budget'], 'max_faults': post['max_faults'],
        'budget_denominator': ('post-response stage exact ordered faults and '
                               'same moved-session/leader owner guard after last fault'),
        'cluster_test': 'org.apache.zookeeper.test.QuorumTest#testSessionMoved',
        'cluster_nodes': 5, 'source_path': source['source_path'],
        'source_line': source['source_line'], 'function': source['function'],
        'check_code': source['check_code'],
        'original_source_commit': post['original_source_commit'],
        'methodology': 'original_cluster_junit_actor_v2_asm_line_feedback_two_fault_families',
        'graphchecker_or_skeleton_runtime_dependency': False,
        'actor_identity': ('actual moved-session ClientCnxn/NIOServerCnxn, '
                           'peer SID, leader owner object, and raw session ID'),
        'fault_model': ('ordered IOException before bound socket I/O and, in a '
                        'separate stage, after complete client write/server response'),
        'fault_trials': total_fault_trials, 'fully_applied_trials': total_exact,
        'strict_injections': total_exact, 'target_after_fault': total_effective,
        'post_fault_target_reach_trials': total_effective,
        'selected_target_throw_events': 0,
        'healthy_target_throw_count_per_seed': [0, 0],
        'coverage_gain': pre['effective_coverage_gain'] + post['effective_coverage_gain'],
        'io_family_gain': {'pre_io': pre['effective_io_family_gain'],
                           'post_response': post['effective_io_family_gain']},
        'coverage_feedback': 'ASM production source-line IDs in instrumented methods',
        'elapsed_seconds': round(pre['elapsed_seconds'] + post['healthy_seconds'] +
                                 post['trial_seconds'], 3),
        'elapsed_measurement': ('sum of original-JUnit JVM times across two separate '
                                'actor-aware fault-family stages'),
        'bug_mark': 'none', 'new_bug': False, 'known_bug': False,
        'target_reached': True,
        'reason': ('Two fresh healthy original cluster JUnits were calibrated per '
                   'stage. Raw receipts prove the selected moved session, leader '
                   'owner, exact ordered faults and post-final-fault guard. No '
                   'selected SessionExpiredException was observed.'),
        'pre_io_stage': {
            'status': pre['status'], 'selected_attempts': pre['selected_attempts'],
            'exact_fault_plans': pre['exact_fault_plans'], 'effective': pre['effective'],
            'effective_budget': pre['effective_budget'],
            'elapsed_seconds': pre['elapsed_seconds'],
            'coverage_gain': pre['effective_coverage_gain'],
            'raw_archive_sha256': pre['raw_archive_sha256'],
        },
        'post_response_stage': {
            'status': post['status'], 'selected_attempts': post['selected_attempts'],
            'exact_fault_plans': post['exact_fault_plans'], 'effective': post['effective'],
            'effective_budget': post['effective_budget'],
            'elapsed_seconds': round(post['healthy_seconds'] + post['trial_seconds'], 3),
            'coverage_gain': post['effective_coverage_gain'],
            'max_faults': post['max_faults'],
        },
        'conditional_extension': {'extended': post['effective_budget'] == 128,
                                  'effective_target': post['effective_budget']},
        'limitations': [
            'The two fault families have separate agents, healthy seeds, and feedback; their effective denominators are not pooled to satisfy the 80-trial stage budget.',
            'This result covers the original selected embedded-cluster JUnit, not every workload.',
            'ASM line feedback covers instrumented production methods, not the full codebase.'
        ],
        'evidence': {
            'pre_io_summary': '../../zk-actor-v2/cases/ZOOKEEPER-03/evidence/pre-io-summary.json',
            'pre_io_audit': '../../zk-actor-v2/cases/ZOOKEEPER-03/evidence/terminal-audit.json',
            'pre_io_archive': '../../zk-actor-v2/cases/ZOOKEEPER-03/evidence/raw-runs.tar.gz',
            'pre_io_trial_table': '../../zk-actor-v2/cases/ZOOKEEPER-03/evidence/pre-io-trials.csv',
            'post_response_audit': '../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/terminal-audit.json',
            'post_response_audit_sha256': sha(AUDIT),
            'post_response_archive': '../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/raw-runs.tar.gz',
            'post_response_archive_sha256': sha(ARCHIVE),
            'post_response_build': '../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/build-receipt.json',
            'post_response_build_sha256': sha(BUILD),
            'post_response_trial_table': '../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/trial-times.csv',
            'post_response_trial_table_sha256': sha(TABLE),
            'historical_result': 'result.pre-actor-v2.json',
            'historical_result_sha256': sha(HISTORICAL),
        },
        'legacy_coarse_actor': old.get('legacy_coarse_actor'),
        'trial_results_scope': 'actor_v2_original_junit_two_separate_fault_families',
    }
    RESULT.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    old_readme = README.with_name('README.pre-actor-v2.md')
    if README.exists() and not old_readme.exists():
        shutil.copy2(README, old_readme)
    README.write_text(
        '# ZOOKEEPER-03 actor-aware original-JUnit result\n\n'
        'The unchanged `QuorumTest#testSessionMoved` runs an embedded five-peer '
        'cluster and exercises `SessionTrackerImpl.setOwner`. Fault selectors '
        'bind the actual moved client session, peer and leader owner. Only the '
        'same selected guard after the final fault counts.\n\n'
        f'The pre-I/O stage ended at 480 selected JUnits with 37 effective. '
        f'The separate post-response stage ended at {post["selected_attempts"]} '
        f'selected JUnits with {post["effective"]} effective, versus its '
        f'{post["effective_budget"]}/max{post["max_faults"]} budget. '
        f'Together the stages consumed {result["elapsed_seconds"]} summed '
        f'original-JUnit JVM seconds. The table reports {total_fault_trials} '
        f'fault trials, {total_exact} exact plans and {total_effective} '
        'postfault target reaches across both stages. Their feedback queues '
        'and budget denominators remain separate.\n\n'
        f'Effective faulted runs added {result["coverage_gain"]} instrumented '
        f'production source-line IDs. No selected SessionExpiredException was '
        f'observed. Result: **{result["status"]}**, bug mark `none`.\n\n'
        'The [pre-I/O audit](../../zk-actor-v2/cases/ZOOKEEPER-03/evidence/terminal-audit.json), '
        '[post-response audit](../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/terminal-audit.json), '
        '[per-trial times](../../zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/trial-times.csv), '
        'and raw archives in the same evidence directories preserve all original '
        'JUnit receipts, actor joins, coverage, and applied plans. The older '
        'global-ordinal [result](result.pre-actor-v2.json) remains coarse history.\n')
    print(json.dumps({'status': result['status'], 'fault_trials': total_fault_trials,
                      'effective_across_stages': total_effective,
                      'post_stage_effective': post['effective'],
                      'elapsed_seconds': result['elapsed_seconds']}, sort_keys=True))


if __name__ == '__main__':
    main()
