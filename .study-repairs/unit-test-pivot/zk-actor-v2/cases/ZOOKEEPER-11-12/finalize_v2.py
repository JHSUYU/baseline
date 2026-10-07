#!/usr/bin/env python3
"""Publish the terminal, raw-audited shared JUnit run as two separate check results."""

import csv
import hashlib
import json
from pathlib import Path
import shutil


CASE = Path(__file__).resolve().parent
BASE = CASE.parents[2]
AUDIT = CASE / 'evidence' / 'campaign-audit.json'
TABLE = CASE / 'evidence' / 'trial-summary.csv'
ARCHIVE = CASE / 'evidence' / 'raw-runs.tar.gz'
BUILD_RECEIPT = CASE / 'evidence' / 'build-receipt.json'
CALIBRATION = CASE / 'evidence' / 'calibration-receipt.json'
RUN_ROOT = '/users/ZhenyuLi/zk1112-actor-v2-runs'
TEST = ('org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest'
        '.testReadCurrentEpochFromAcceptedEpochTmpFile')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               sort_keys=True) + '\n')


def table(audit):
    fields = ['run_id', 'selected_plan_for', 'elapsed_seconds', 'fault_depth',
              'exact', 'applied_faults', 'junit_exit', 'new_coverage_lines',
              'new_io_families', 'zk11_effective', 'zk11_postfault_guards',
              'zk11_target_throws', 'zk12_effective', 'zk12_postfault_guards',
              'zk12_target_throws', 'events_sha256', 'coverage_sha256',
              'receipt_sha256']
    with TABLE.open('w', newline='') as output:
        writer = csv.DictWriter(output, fields)
        writer.writeheader()
        for row in audit['trials']:
            writer.writerow({
                'run_id': row['run_id'], 'selected_plan_for': row['case'],
                'elapsed_seconds': row['elapsed_seconds'],
                'fault_depth': row['fault_depth'], 'exact': row['exact'],
                'applied_faults': row['applied_faults'],
                'junit_exit': row['junit_exit'],
                'new_coverage_lines': row['new_coverage_lines'],
                'new_io_families': row['new_io_families'],
                'zk11_effective': row['cases']['ZOOKEEPER-11']['effective'],
                'zk11_postfault_guards': row['cases']['ZOOKEEPER-11']['postfault_guards'],
                'zk11_target_throws': row['cases']['ZOOKEEPER-11']['target_throws'],
                'zk12_effective': row['cases']['ZOOKEEPER-12']['effective'],
                'zk12_postfault_guards': row['cases']['ZOOKEEPER-12']['postfault_guards'],
                'zk12_target_throws': row['cases']['ZOOKEEPER-12']['target_throws'],
                'events_sha256': row['events_sha256'],
                'coverage_sha256': row['coverage_sha256'],
                'receipt_sha256': row['receipt_sha256'],
            })


def main():
    audit = json.loads(AUDIT.read_text())
    if audit['status'] not in ('complete', 'queue_exhausted', 'selected_cap') or \
            audit['inflight'] is not None or audit['completed'] != len(audit['trials']):
        raise RuntimeError('raw audit does not describe a terminal JUnit boundary')
    if audit['original_source_commit'] != '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae':
        raise RuntimeError('original ZooKeeper source revision changed')
    if audit['selected'] != audit['completed'] + audit['interrupted']:
        raise RuntimeError('selected plans are not accounted for')
    if sum(item['selected_target_throw_events'] for item in audit['cases'].values()):
        raise RuntimeError('selected target throw requires source review and replay first')
    if not ARCHIVE.is_file():
        raise RuntimeError('raw original-JUnit archive not present')
    if not BUILD_RECEIPT.is_file() or not CALIBRATION.is_file() or \
            sha(CALIBRATION) != audit['calibration_sha256']:
        raise RuntimeError('offline build or healthy calibration receipt absent/changed')
    build = json.loads(BUILD_RECEIPT.read_text())
    calibration = json.loads(CALIBRATION.read_text())
    if build['agent_sha256'] != audit['agent_sha256'] or \
            build['source_commit'] != audit['original_source_commit'] or \
            build['junit_executed'] or calibration['first_server_sid'] != '0' or \
            any(seed['status'] != 'pass' for seed in calibration['healthy']):
        raise RuntimeError('offline build disagrees with original JUnit audit')
    table(audit)
    case_summaries = {}
    for case_id in ('ZOOKEEPER-11', 'ZOOKEEPER-12'):
        case_dir = BASE / 'cases' / case_id
        result_path = case_dir / 'result.json'
        old_path = case_dir / 'result.pre-actor-v2.json'
        if not old_path.exists():
            shutil.copy2(result_path, old_path)
        old = json.loads(old_path.read_text())
        if old['case_id'] != case_id or old['status'] != 'actor_identity_recheck_pending':
            raise RuntimeError(case_id + ' historical result changed')
        measured = audit['cases'][case_id]
        complete = (audit['status'] == 'complete' and
                    measured['effective'] >= measured['effective_target'])
        result = {
            'case_id': case_id, 'system': 'ZooKeeper 3.8.7',
            'status': 'quality_complete' if complete else 'inconclusive_budget_unmet',
            'quality_complete': complete, 'campaign_finished': True,
            'campaign_budget': measured['effective_target'],
            'budget_denominator': ('exact ordered actor/file IOException faults and '
                                   'the original firstServer peer0 selected guard '
                                   'after the final applied fault'),
            'cluster_test': TEST, 'cluster_nodes': 3,
            'source_file': ('zookeeper-server/src/main/java/org/apache/zookeeper/'
                            'server/quorum/QuorumPeer.java'),
            'source_line': 1175 if case_id.endswith('11') else 1197,
            'function': 'org.apache.zookeeper.server.quorum.QuorumPeer.loadDataBase()',
            'target_guard_line': 1169 if case_id.endswith('11') else 1193,
            'healthy_target_guard_count_per_seed': [
                seed['guard_counts'][case_id] for seed in calibration['healthy']],
            'healthy_bound_io_count_per_seed': [
                seed['bound_io_count'] for seed in calibration['healthy']],
            'healthy_stable_selectors': len(calibration['common_selectors']),
            'check_code': old.get('check_code') or (
                'if (currentTmp.exists()) restore its epoch; else throw IOException '
                'because currentEpoch is older than the last zxid'
                if case_id.endswith('11') else
                'if (acceptedEpoch < currentEpoch) throw IOException'),
            'original_source_commit': audit['original_source_commit'],
            'methodology': 'original_cluster_junit_actor_file_v2_asm_line_feedback',
            'graphchecker_or_skeleton_runtime_dependency': False,
            'limitations': [
                'The fault model covers bound epoch-file reads, writes, temporary-file '
                'open, and rename; AtomicFileOutputStream.close FileDescriptor.sync '
                'and socket or ZooKeeper API I/O have no separate injection hook.',
                'ASM line feedback covers instrumented QuorumPeer and '
                'AtomicFileOutputStream methods, not the entire production codebase.',
                'Results apply to the original selected embedded-cluster JUnit and '
                'source-specific target exception, not every workload or fault type.',
            ],
            'actor_identity': ('actual QuorumPeer.myid and normalized epoch File '
                               'from receiver; firstServer peer0 target after final fault'),
            'fault_model': 'ordered java.io.IOException at bound epoch file I/O',
            'fault_trials': audit['completed'],
            'selected_plan_attempts': measured['selected_plan_attempts'],
            'strict_injections': audit['strict_injection_trials'],
            'fully_applied_trials': audit['strict_injection_trials'],
            'strict_but_target_lost': measured['strict_but_target_lost'],
            'target_after_fault': measured['effective'],
            'post_fault_target_reach_trials': measured['effective'],
            'selected_target_throw_events': measured['selected_target_throw_events'],
            'target_exception_after_fault_trials': measured['selected_target_throw_trials'],
            'junit_nonzero_trials': audit['junit_nonzero_trials'],
            'effective_junit_nonzero_trials': measured['effective_junit_nonzero'],
            'max_fault_depth_attempted': audit['max_fault_depth_attempted'],
            'max_fault_depth_selected': measured['max_fault_depth_selected'],
            'max_faults': measured['max_faults'],
            'coverage_feedback': ('ASM source-line coverage of QuorumPeer and '
                                  'AtomicFileOutputStream production methods'),
            'healthy_coverage_lines': audit['healthy_coverage_lines'],
            'coverage_gain': measured['observed_coverage_gain'],
            'io_family_gain': measured['observed_io_family_gain'],
            'healthy_io_families': measured['healthy_io_families'],
            'elapsed_seconds': round(audit['healthy_elapsed_seconds'] +
                                     audit['trial_elapsed_seconds'], 3),
            'elapsed_measurement': ('shared two-healthy plus all original-JUnit fault '
                                    'JVM elapsed time, reported for each of two checks; '
                                    'do not add the two case totals'),
            'healthy_elapsed_seconds': audit['healthy_elapsed_seconds'],
            'trial_elapsed_seconds': audit['trial_elapsed_seconds'],
            'effective_trial_seconds': measured['effective_trial_seconds'],
            'bug_mark': 'none', 'known_bug': False, 'new_bug': False,
            'target_reached': True,
            'reason': ('Two fresh healthy original embedded-cluster JUnits reached '
                       'the selected firstServer peer0 guard. Raw receipts, file '
                       'owner, ordered fault applications, post-final-fault guard, '
                       'coverage, and I/O-family feedback were re-audited. No '
                       'source-specific selected throw occurred.'),
            'stop_reason': (str(measured['effective_target']) +
                            '_effective_budget_complete' if complete else
                            audit['status'] + '_before_effective_budget'),
            'conditional_extension': {
                'decided': measured['extension_decided'],
                'novelty_at_eighty': measured['extension_novelty_at_eighty'],
                'effective_target': measured['effective_target'],
            },
            'new_methodology_run_root': RUN_ROOT,
            'v2_campaign_audit': '../../zk-actor-v2/cases/ZOOKEEPER-11-12/evidence/campaign-audit.json',
            'v2_campaign_audit_sha256': sha(AUDIT),
            'v2_build_receipt': '../../zk-actor-v2/cases/ZOOKEEPER-11-12/evidence/build-receipt.json',
            'v2_build_receipt_sha256': sha(BUILD_RECEIPT),
            'v2_calibration_receipt': '../../zk-actor-v2/cases/ZOOKEEPER-11-12/evidence/calibration-receipt.json',
            'v2_calibration_receipt_sha256': sha(CALIBRATION),
            'v2_trial_table': '../../zk-actor-v2/cases/ZOOKEEPER-11-12/evidence/trial-summary.csv',
            'v2_trial_table_sha256': sha(TABLE),
            'v2_raw_archive': '../../zk-actor-v2/cases/ZOOKEEPER-11-12/evidence/raw-runs.tar.gz',
            'v2_raw_archive_sha256': sha(ARCHIVE),
            'historical_result': 'result.pre-actor-v2.json',
            'historical_result_sha256': sha(old_path),
            'legacy_coarse_actor': old.get('legacy_coarse_actor'),
            'trial_results_scope': 'actor_v2_original_junit_shared_two_checks',
        }
        write_json(result_path, result)
        case_summaries[case_id] = {'effective': measured['effective'],
                                   'target': measured['effective_target'],
                                   'status': result['status'],
                                   'elapsed_seconds': result['elapsed_seconds'],
                                   'result_sha256': sha(result_path)}
    print(json.dumps(case_summaries, sort_keys=True))


if __name__ == '__main__':
    main()
