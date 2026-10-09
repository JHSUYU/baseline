#!/usr/bin/env python3
"""Publish ZK02's audited two-stage V2 outcome without old coarse counts."""

import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[3] / 'cases' / 'ZOOKEEPER-02'
AUDIT = HERE / 'campaign-audit.json'
TABLE = HERE / 'trial-summary.csv'
OLD = Path('/users/ZhenyuLi/zk02-actor-v2-runs/v2-campaign.json')
PREVIOUS = CASE / 'result.pre-actor-v2.json'
RESULT = CASE / 'result.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    audit = json.loads(AUDIT.read_text())
    if (audit['status'] != 'pass' or audit['aggregate_effective'] != 80
            or audit['aggregate_attempts'] != 85
            or audit['conditional_extension_required']):
        raise RuntimeError('final actor-aware audit is not the expected terminal 80')
    if not PREVIOUS.exists():
        shutil.copy2(RESULT, PREVIOUS)
    old = json.loads(OLD.read_text())
    if (old['status'] != 'paused_for_semantic_diagnosis'
            or len(old['results']) != 113 or old['effective_count'] != 0):
        raise RuntimeError('excluded pre-I/O checkpoint changed')
    client, server = audit['stages']
    if (client['status'] != 'queue_exhausted' or server['status'] != 'budget_complete'
            or client['effective'] != 20 or server['effective'] != 60
            or client['selected_target_throws'] or server['selected_target_throws']):
        raise RuntimeError('stage terminal counts changed')
    result = {
        'case_id': 'ZOOKEEPER-02', 'system': 'ZooKeeper 3.8.7',
        'status': 'quality_complete', 'quality_complete': True,
        'source_inventory_only': False,
        'cluster_test': 'org.apache.zookeeper.test.QuorumTest#testSessionMoved',
        'target_method': '<org.apache.zookeeper.server.SessionTrackerImpl: '
                         'void checkSession(long,java.lang.Object)>',
        'target_source_file': 'zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java',
        'target_source_line': 323,
        'target_code': 'else if (session.owner != owner) { throw new KeeperException.SessionMovedException(); }',
        'original_source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
        'methodology': 'original_cluster_junit_actor_v2_complete_io_asm_line_feedback',
        'graphchecker_or_skeleton_runtime_dependency': False,
        'actor_identity': 'actual client handle/socket destination or server peer/connection; '
                          'one raw moved session; actual leader SID and prior/request owner objects',
        'budget_denominator': 'fully applied ordered actor-aware plans with same-session '
                              'owner receipt and selected target guard after final fault',
        'campaign_budget': 80, 'campaign_finished': True,
        'fault_trials': 85, 'strict_injections': 80,
        'fully_applied_trials': 80, 'target_after_fault': 80,
        'post_fault_target_reach_trials': 80,
        'target_exception_after_fault_trials': 0,
        'selected_target_throw_events': 0,
        'healthy_target_guard_count_per_seed': 20,
        'healthy_target_throw_count': 0,
        'max_fault_depth_attempted': 6, 'max_faults': 8,
        'coverage_feedback': 'case-local ASM production source-line coverage.tsv; '
                             'JaCoCo exec not collected',
        'healthy_coverage_lines': audit['aggregate_healthy_coverage_lines'],
        'effective_cumulative_coverage_lines': audit['aggregate_effective_coverage_lines'],
        'coverage_gain': audit['aggregate_effective_coverage_gain'],
        'coverage_gain_all_attempts': audit['aggregate_effective_coverage_gain'],
        'target_related_io_families': audit['aggregate_target_related_io_families'],
        'io_family_gain': sum(stage['new_target_related_io_families']
                              for stage in audit['stages']),
        'elapsed_measurement': 'sum of four original-JUnit healthy JVMs and 85 counted '
                               'fault JVMs; two fault workers ran concurrently; '
                               'excludes pilot/development/audit time',
        'healthy_elapsed_seconds': round(sum(stage['healthy_elapsed_seconds']
                                             for stage in audit['stages']), 3),
        'trial_elapsed_seconds': round(sum(stage['trial_elapsed_seconds']
                                           for stage in audit['stages']), 3),
        'elapsed_seconds': audit['aggregate_elapsed_seconds'],
        'active_campaign_wall_seconds': round(sum(stage['fault_campaign_wall_seconds']
                                                  for stage in audit['stages']), 3),
        'junit_non_target_failure_trials': sum(stage['non_target_junit_failures']
                                               for stage in audit['stages']),
        'bug_mark': 'none', 'known_bug': False, 'new_bug': False,
        'target_reached': True,
        'reason': 'Two fresh original-cluster JUnit calibrations per agent variant passed. '
                  'Twenty complete client-write faults and sixty complete server sync-response '
                  'fault sequences retained the same moved-session owner check after the final '
                  'fault. No selected SessionMovedException occurred. The twenty client-stage '
                  'ConnectionLoss JUnit outcomes are separate non-target failures.',
        'stop_reason': '80_effective_budget_complete; last eight effective trials added '
                       'no selected target throw, ASM line, or bound I/O family; '
                       '128/10 conditional extension not triggered',
        'old_pre_io_excluded': {
            'attempts': 113, 'effective': 0,
            'status': old['status'], 'faults_applied': 113,
            'postfault_selected_guard': 0,
            'checkpoint': str(OLD), 'checkpoint_sha256': sha(OLD),
            'reason': 'pre-I/O socket exception aborted synchronous original JUnit operations '
                      'before the next owner check; never contributes to current denominator',
        },
        'v2_stages': [
            {'name': stage['stage'], 'attempts': stage['attempts'],
             'effective': stage['effective'], 'status': stage['status'],
             'max_fault_depth': stage['max_depth'],
             'selected_target_throws': stage['selected_target_throws'],
             'non_target_junit_failures': stage['non_target_junit_failures'],
             'coverage_gain': stage['effective_coverage_gain'],
             'new_io_families': stage['new_target_related_io_families'],
             'healthy_elapsed_seconds': stage['healthy_elapsed_seconds'],
             'trial_elapsed_seconds': stage['trial_elapsed_seconds'],
             'fault_campaign_wall_seconds': stage['fault_campaign_wall_seconds'],
             'agent_sha256': stage['agent_sha256'],
             'run_root': '/users/ZhenyuLi/zk02-actor-v2-afterio-runs'
                         if index == 0 else '/users/ZhenyuLi/zk02-actor-v2-after-response-runs'}
            for index, stage in enumerate(audit['stages'])
        ],
        'v2_campaign_audit': '../../zk-actor-v2/cases/ZOOKEEPER-02/after-response/campaign-audit.json',
        'v2_campaign_audit_sha256': sha(AUDIT),
        'v2_trial_table': '../../zk-actor-v2/cases/ZOOKEEPER-02/after-response/trial-summary.csv',
        'v2_trial_table_sha256': sha(TABLE),
        'historical_result': 'result.pre-actor-v2.json',
        'historical_result_sha256': sha(PREVIOUS),
        'trial_results_scope': 'actor_v2_two_complete_io_stages_only',
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'case': 'ZOOKEEPER-02', 'status': result['status'],
                      'effective': result['target_after_fault'],
                      'elapsed_seconds': result['elapsed_seconds'],
                      'result_sha256': sha(RESULT)}, sort_keys=True))


if __name__ == '__main__':
    main()
