#!/usr/bin/env python3
"""Independently reparse HBASE-16 and package its original-JUnit evidence."""
import hashlib
import json
from pathlib import Path
import tarfile

from campaign import CASE, HERE, RESULT, EXPECTED, coverage, parse, save


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    data = json.loads(RESULT.read_text())
    assert data['status'] in ('quality_complete', 'candidate_review')
    assert data['healthy_junit_passed']
    assert data['healthy_expected_target_exception_count'] > 0
    assert data['healthy_target_throw_line_371_covered']
    items = data['fault_trial_details']
    assert len(items) == data['fault_trials']
    assert len({item['plan'] for item in items}) == len(items)
    valid_paths = [HERE / 'healthy_final.exec']
    for item in items:
        fresh = parse(item['id'], item['plan'])
        for key in ('requested_fault_events', 'matched_fault_events',
                    'applied_fault_events', 'applied_selector_sequence', 'strict',
                    'target_after_final_fault', 'junit_passed', 'junit_exit',
                    'target_expected_exception_count'):
            assert fresh[key] == item[key], (item['id'], key, fresh[key], item[key])
        assert len(item['plan'].split(',')) <= data['fault_budget']['max_faults_per_trial']
        for event in item['observed_io']:
            if event['applied']:
                assert event['door'] == 'MOVE_MASTER_RPC'
        assert all(call['exception'] == EXPECTED
                   for call in item['post_fault_expected_target_exits'])
        item['bug_mark'] = ('candidate_review' if item['strict']
            and item['target_after_final_fault']
            and (item['post_fault_unexpected_target_exits'] or not item['junit_passed'])
            else 'none')
        exe = HERE / (item['id'] + '.exec')
        assert exe.exists(), exe
        if item['strict'] and item['target_after_final_fault']:
            valid_paths.append(exe)
    assert data['strict_injections'] == sum(item['strict'] for item in items)
    assert data['target_after_fault'] == sum(
        item['strict'] and item['target_after_final_fault'] for item in items)
    assert data['requested_fault_events'] == sum(
        item['requested_fault_events'] for item in items)
    assert data['matched_fault_events'] == sum(
        item['matched_fault_events'] for item in items)
    assert data['applied_fault_events'] == sum(
        item['applied_fault_events'] for item in items)
    union = coverage(valid_paths)
    assert 'error' not in union
    assert data['coverage_gain'] == (union['total_branches']
                                    - data['healthy_coverage']['total_branches'])
    data['target_throw_line_371_covered_after_fault'] = any(
        item['production_coverage'].get('target_lines', {}).get('371', {})
        .get('instructions', 0) > 0 for item in items)
    data['instrumentation_provenance'] = {
        'counted_runtime': 'Unchanged original JUnit, case-local ByteBuddy and JaCoCo',
        'graphchecker_jar_used': False,
        'prewoven_classes_used': False,
        'region_skeletons_or_static_scope_map_read': False,
        'static_aggregate_or_closure_run': False,
        'original_test_modified': False,
        'guard_evidence': 'Exact confirmClosed HBaseIOException on the Backoff region, '
                          'whose source-exclusive throw is line 371; JaCoCo covers line 371. '
                          'The attempted direct isInState advice emitted no GUARD markers.'}
    data['calibration_reuse'] = {
        'r001': 'Original calibrate01 files renamed without rerun',
        'r002': 'Original calibrate08 files renamed without rerun'}
    evidence = CASE / 'evidence'
    evidence.mkdir(exist_ok=True)
    files = [CASE / 'README.md', HERE / 'run.sh', HERE / 'campaign.py',
             HERE / 'prefetch.py',
             HERE / 'finalize.py', HERE / 'src' / 'HBase16Agent.java',
             HERE / 'src' / 'NativeJUnit.java', HERE / 'src' / 'CoverageReport.java',
             HERE / 'source' / 'TransitRegionStateProcedure.java',
             HERE / 'source' / 'TestCloseRegionWhileRSCrash.java',
             HERE / 'source' / 'HBaseAdmin.java',
             HERE / 'source' / 'MasterCallable.java',
             HERE / 'source' / 'revision.txt',
             HERE / 'original-mapping-result.json', HERE / 'agent.jar',
             HERE / 'agent-healthy-v2.jar', HERE / 'agent-healthy-v3.jar',
             HERE / 'manifest.mf',
             HERE / 'junit-platform-launcher-1.13.4.jar', HERE / 'healthy_final.log',
             HERE / 'healthy_final.exec', HERE / 'healthy_final.exit']
    for item in items:
        for suffix in ('.log', '.exec', '.exit'):
            files.append(HERE / (item['id'] + suffix))
    for suffix in ('startup_probe', 'healthy_v2', 'healthy_v3',
                   'campaign', 'prefetch'):
        files.extend(path for extension in ('.log', '.exec', '.exit')
                     if (path := HERE / (suffix + extension)).exists())
    assert all(path.exists() for path in files)
    data['evidence'].update({
        'readme': 'README.md', 'archive': 'evidence/hbase16-native-evidence.tar.gz',
        'manifest': 'evidence/native-manifest.json',
        'trial_logs': 'native/r001.log through native/r%03d.log' % len(items),
        'trial_coverage': 'Matching native/rNNN.exec files',
        'source_snapshot': 'native/source/ at HBase rel/2.6.6'})
    save(data)
    archive = evidence / 'hbase16-native-evidence.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(CASE)))
    manifest = {
        'archive': str(archive.relative_to(CASE)), 'archive_sha256': sha256(archive),
        'file_count': len(files),
        'files': {str(path.relative_to(CASE)): sha256(path) for path in files}}
    (evidence / 'native-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    data['evidence']['archive_sha256'] = manifest['archive_sha256']
    save(data)


if __name__ == '__main__':
    main()
