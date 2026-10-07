#!/usr/bin/env python3
"""Publish the reviewed HBASE-21 result after main and manifest campaigns end."""
import datetime
import json
import os
from pathlib import Path

case = Path(__file__).resolve().parent.parent
result_path = case / 'result.json'
result = json.loads(result_path.read_text())
manifest = json.loads((case / 'work/manifest/result.json').read_text())
checkpoint = json.loads((case / 'work/checkpoint.json').read_text())

assert result['effective_trials'] == 128
assert result['current_campaign']['junit_failures_after_target'] == 0
assert result['current_campaign']['strict_post_fault_unexpected_region_quota_trials'] == 0
assert len(manifest['fault_trials']) == 2
assert all(x['strict'] and not x['target_after_fault'] for x in manifest['fault_trials'])

main_trial_elapsed = result['current_campaign']['elapsed_seconds']
main_wall = result['current_campaign']['wall_seconds_since_healthy']
main_healthy = result['healthy_elapsed_seconds']
finished = (case / 'work/manifest/logs/m004.log').stat().st_mtime
began = checkpoint['started_unix'] - main_healthy
result.update({
    'status': 'quality_complete',
    'quality_complete': True,
    'methodology': 'coverage_io_no_graph',
    'source_review_complete': True,
    'bug_mark': 'none',
    'bug_candidates': [],
    'elapsed_seconds': round(finished - began, 2),
    'started_at_utc': datetime.datetime.fromtimestamp(
        began, datetime.timezone.utc).isoformat(),
    'completed_at_utc': datetime.datetime.fromtimestamp(
        finished, datetime.timezone.utc).isoformat(),
    'elapsed_basis': 'Wall time from main original-JUnit healthy start through '
                     'manifest calibration final log mtime; includes scheduling '
                     'pauses and source review.',
    'timing': {
        'main_original_junit_healthy_seconds': main_healthy,
        'main_completed_trial_runtime_seconds': main_trial_elapsed,
        'main_wall_seconds_since_healthy': main_wall,
        'manifest_original_junit_healthy_and_two_fault_trials_seconds':
            manifest['total_elapsed_seconds'],
        'case_wall_seconds': round(finished - began, 2),
    },
    'stopping_reason': 'Authorized 128 strict target-retaining trials reached; '
                       'one conditional extension from 80, no further expansion.',
    'manifest_supplement': {
        'status': 'complete_target_lost_excluded',
        'result': 'work/manifest/result.json',
        'original_junit_healthy_passed': manifest['healthy']['junit'] ==
            {'found': 1, 'succeeded': 1, 'failed': 0},
        'original_junit_healthy_elapsed_seconds': manifest['healthy']['elapsed_seconds'],
        'observed_actual_restore_manifest_selectors': manifest['candidate_selectors'],
        'completed_fault_trials': len(manifest['fault_trials']),
        'strict_fault_trials': sum(x['strict'] for x in manifest['fault_trials']),
        'target_after_fault_trials': sum(x['target_after_fault']
                                         for x in manifest['fault_trials']),
        'junit_failures': sum(x['junit_exit'] != 0 for x in manifest['fault_trials']),
        'elapsed_seconds': manifest['total_elapsed_seconds'],
        'excluded_from_main_budget': True,
        'source_review': 'Both real DistributedFileSystem.open IOException injections '
                         'occur in SnapshotManifest.readDataManifest before '
                         'RestoreSnapshotProcedure.prepareRestore calls '
                         'checkAndUpdateNamespaceRegionQuota. The IOException '
                         'propagates through SnapshotManifest.open; restore fails '
                         'and the log reports successful rollback. The original '
                         'JUnit then fails because its expected QuotaExceededException '
                         'cause is absent. Exact B3 check is not reached after '
                         'either fault, so both trials are excluded under the '
                         'selected-target rule.',
        'abandoned_initial_temporary_snapshot_calibration':
            manifest.get('abandoned_calibration_trial'),
    },
    'source_review': {
        'target_source': 'NamespaceStateManager.checkAndUpdateNamespaceRegionCount'
                         '(TableName,int), HBase 2.6.6 source line 133',
        'target_condition': 'namespaceTotal - priorTableRegions + '
                            'requestedSnapshotRegions > namespaceMaxRegions',
        'healthy_values': {'namespace_total': 1, 'prior_table_regions': 1,
                           'requested_snapshot_regions': 4, 'max_regions': 3},
        'original_junit': 'TestNamespaceAuditor.testRestoreSnapshotQuotaExceed, '
                          'lines 701-742',
        'original_junit_assertion': 'The test explicitly expects '
                                    'RestoreSnapshotException caused by '
                                    'QuotaExceededException and checks the '
                                    'namespace count remains one.',
        'main_fault_outcome': 'All 128 strict target-retaining trials '
                              're-executed the exact guard, saw the expected '
                              'quota exception and passed the unchanged '
                              'original JUnit; zero unexpected target '
                              'exceptions or post-target JUnit failures.',
        'manifest_boundary': 'Two strict actual restore-manifest DFS.open '
                             'IOException trials lost the target before the '
                             'quota guard; test failures are excluded and '
                             'do not prove a new bug.',
        'instrumentation_provenance': 'Case-local runtime ByteBuddy target/ZK '
                                      'I/O probe, case-local DFS.open ByteBuddy '
                                      'supplement and JaCoCo coverage on '
                                      'original release JAR/test JAR; no '
                                      'GraphChecker skeleton, static map, '
                                      'graph or closure.',
    },
    'quality_completion_note': 'Original embedded two-master JUnit healthy '
                               'seed and 128 distinct strict fault sequences '
                               'retaining exact B3 were completed. A separate '
                               'two-selector real manifest-file I/O '
                               'calibration documented the target-loss '
                               'boundary. Per-trial UTC time, identity, '
                               'target/JUnit and production coverage are '
                               'in work/trial_ledger.json; full checkpoint '
                               'remains in work/checkpoint.json.',
})
for evidence in ('work/trial_ledger.json', 'work/checkpoint.json',
                 'work/checkpoint.json.gz', 'work/manifest/result.json',
                 'work/manifest/evidence_logs.tar.gz'):
    if evidence not in result['evidence']:
        result['evidence'].append(evidence)
temp = result_path.with_suffix('.tmp')
temp.write_text(json.dumps(result, indent=2) + '\n')
os.replace(temp, result_path)
print(result['status'], result['fault_trials'], result['effective_trials'],
      result['elapsed_seconds'], result['manifest_supplement']['status'])
