#!/usr/bin/env python3
"""Reparse the HBASE-18 original-JUnit ledger and package case evidence."""
import hashlib
import json
from pathlib import Path
import tarfile

from campaign import CASE, HERE, RESULT, coverage, parse, save


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
    assert data['healthy_guard_marker_count'] == 1
    assert data['healthy_guard_max'] == 3
    assert data['healthy_target_guard_line_323_covered']
    assert not data['healthy_target_throw_line_325_covered']
    items = data['fault_trial_details']
    assert data['fault_trials'] == len(items)
    assert len({item['plan'] for item in items}) == len(items)
    valid_paths = [HERE / 'healthy_counted.exec']
    for item in items:
        fresh = parse(item['id'], item['plan'])
        for key in ('requested_fault_events', 'matched_fault_events',
                    'applied_fault_events', 'applied_selector_sequence', 'strict',
                    'same_request_faults', 'target_after_final_fault',
                    'selected_exception_observed', 'junit_passed', 'junit_exit'):
            assert fresh[key] == item[key], (item['id'], key, fresh[key], item[key])
        assert len(item['plan'].split(',')) <= data['fault_budget']['max_faults_per_trial']
        exe = HERE / (item['id'] + '.exec')
        assert exe.exists(), exe
        if item['strict'] and item['same_request_faults'] and item['target_after_final_fault']:
            valid_paths.append(exe)
    assert data['strict_injections'] == sum(item['strict'] for item in items)
    assert data['target_after_fault'] == sum(
        item['strict'] and item['same_request_faults']
        and item['target_after_final_fault'] for item in items)
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
    data['selected_throw_line_325_covered_after_fault'] = any(
        item['production_coverage'].get('target_lines', {}).get('325', {})
        .get('instructions', 0) > 0 for item in items)
    if data['selected_exception_trials']:
        assert data['selected_throw_line_325_covered_after_fault']
    replay = parse('r002_replay', items[1]['plan'])
    assert (replay['strict'] and replay['same_request_faults']
            and replay['target_after_final_fault']
            and replay['selected_exception_observed'] and replay['junit_passed'])
    data['selected_exception_replay'] = {
        'plan': items[1]['plan'], 'log': 'native/r002_replay.log',
        'strict': replay['strict'], 'same_request_faults': replay['same_request_faults'],
        'post_final_guard': replay['target_after_final_fault'],
        'selected_exception': replay['selected_exception_observed'],
        'original_junit_passed': replay['junit_passed'],
        'elapsed_seconds': replay['elapsed_seconds']}
    data['selected_exception_source_classification'] = (
        'Source line 325 intentionally throws HBaseIOException to back off and retry '
        'after too many failed opens; observed JUnit outcomes are recorded separately.')
    data['instrumentation_provenance'] = {
        'counted_runtime': 'Unchanged original MiniHBaseCluster JUnit, case-local ByteBuddy and JaCoCo',
        'graphchecker_jar_used': False,
        'prewoven_classes_used': False,
        'region_skeletons_or_static_scope_map_read': False,
        'static_aggregate_or_closure_run': False,
        'original_test_modified': False,
        'guard_evidence': 'On the selected test region and TRSP procedure, direct '
                          'getAssignRetryImmediatelyMaxAttempts marker plus JaCoCo line 323; '
                          'source-exclusive selected exception and line 325 identify true arm.'}
    data['calibration_reuse'] = {
        'r001': 'Existing caldnr01 raw files renamed without rerun',
        'r002': 'Existing caldnr04 raw files renamed without rerun'}
    evidence = CASE / 'evidence'
    evidence.mkdir(exist_ok=True)
    files = [CASE / 'README.md', HERE / 'run.sh', HERE / 'campaign.py',
             HERE / 'finalize.py', HERE / 'src' / 'HBase18Agent.java',
             HERE / 'src' / 'NativeJUnit.java', HERE / 'src' / 'CoverageReport.java',
             HERE / 'source' / 'TransitRegionStateProcedure.java',
             HERE / 'source' / 'TestTransitRegionStateProcedure.java',
             HERE / 'source' / 'TestExceptionInAssignRegion.java',
             HERE / 'source' / 'RSProcedureDispatcher.java',
             HERE / 'source' / 'OpenRegionProcedure.java',
             HERE / 'source' / 'AssignmentManager.java',
             HERE / 'source' / 'RegionRemoteProcedureBase.java',
             HERE / 'source' / 'revision.txt', HERE / 'original-mapping-result.json',
             HERE / 'agent.jar', HERE / 'agent-mapped.jar',
             HERE / 'agent-healthy-final2.jar', HERE / 'agent-healthy-final3.jar',
             HERE / 'manifest.mf', HERE / 'junit-platform-launcher-1.13.4.jar',
             HERE / 'healthy_counted.log', HERE / 'healthy_counted.exec',
             HERE / 'healthy_counted.exit']
    for item in items:
        for suffix in ('.log', '.exec', '.exit'):
            files.append(HERE / (item['id'] + suffix))
    for name in ('healthy', 'alt_exception', 'healthy_final', 'healthy_final2',
                 'healthy_final3', 'calibrate01', 'calibrate04',
                 'calconnect01', 'calconnect04', 'campaign',
                 'campaign_adaptive', 'campaign_adaptive_v2',
                 'prefetch', 'r002_replay',
                 'prefetch_aborted_r061', 'prefetch_aborted_r062'):
        files.extend(path for suffix in ('.log', '.exec', '.exit')
                     if (path := HERE / (name + suffix)).exists())
    if (HERE / 'prefetch.py').exists():
        files.append(HERE / 'prefetch.py')
    assert all(path.exists() for path in files)
    data['evidence'].update({
        'readme': 'README.md', 'archive': 'evidence/hbase18-native-evidence.tar.gz',
        'manifest': 'evidence/native-manifest.json',
        'trial_logs': 'native/r001.log through native/r%03d.log' % len(items),
        'trial_coverage': 'Matching native/rNNN.exec files',
        'source_snapshot': 'native/source/ at HBase rel/2.6.6'})
    save(data)
    archive = evidence / 'hbase18-native-evidence.tar.gz'
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
