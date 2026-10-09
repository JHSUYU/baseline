#!/usr/bin/env python3
"""Independently verify the HBASE-35 ledger and archive case-only evidence."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tarfile

from campaign import CASE, HERE, RESULT, coverage, parse, save


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def utc_stamp(time):
    return time.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def trial_evidence(name, elapsed):
    files = {suffix: HERE / (name + '.' + suffix)
             for suffix in ('log', 'exec', 'exit')}
    assert all(path.exists() for path in files.values())
    end = datetime.fromtimestamp(files['exit'].stat().st_mtime, timezone.utc)
    return {
        'started_utc_estimate': utc_stamp(end - timedelta(seconds=elapsed)),
        'finished_utc_checkpoint': utc_stamp(end),
        'utc_method': 'Exit checkpoint file UTC mtime; start estimated by subtracting /usr/bin/time elapsed seconds',
        'sha256': {suffix: sha256(path) for suffix, path in files.items()}}


def main():
    data = json.loads(RESULT.read_text())
    assert data['status'] in ('quality_complete', 'candidate_review')
    assert data['healthy_junit_passed'] and data['healthy_guard_marker_count'] == 3
    assert data['healthy_target_guard_line_2717_covered']
    assert not data['healthy_target_throw_line_2720_covered']
    items = data['fault_trial_details']
    assert len(items) == data['fault_trials']
    assert len({item['plan'] for item in items}) == len(items)
    if data['status'] == 'quality_complete':
        assert len(items) == 80
        assert all(x['strict'] and x['same_full_scan_faults']
                   and x['target_after_final_fault'] and x['junit_passed'] for x in items)
    valid_paths = [HERE / 'healthy_final.exec']
    for item in items:
        fresh = parse(item['id'], item['plan'])
        for key in ('requested_fault_events', 'matched_fault_events',
                    'applied_fault_events', 'applied_selector_sequence',
                    'strict', 'same_full_scan_faults', 'target_after_final_fault',
                    'selected_exception_observed', 'junit_passed', 'junit_exit',
                    'injected_exception_evidence'):
            assert fresh[key] == item[key], (item['id'], key, fresh[key], item[key])
        assert len(item['plan'].split(',')) <= data['fault_budget']['max_faults_per_trial']
        if item['id'] != 'r001':
            raw = (HERE / (item['id'] + '.log')).read_text(errors='replace')
            for event in item['observed_io']:
                if event['applied']:
                    assert ('HBASE35 FAULT_THROW scanId=%d ordinal=%d exception=' %
                            (event['scan_id'], event['ordinal'])) in raw
        exe = HERE / (item['id'] + '.exec')
        assert exe.exists(), exe
        item['raw_evidence'] = trial_evidence(item['id'], item['elapsed_seconds'])
        if (item['strict'] and item['same_full_scan_faults']
                and item['target_after_final_fault'] and item['injected_exception_evidence']):
            assert fresh['target_after_final_fault']
            assert item['production_coverage']['target_lines']['2717']['instructions'] > 0
            valid_paths.append(exe)
    assert data['strict_injections'] == sum(x['strict'] for x in items)
    assert data['target_after_fault'] == sum(
        x['strict'] and x['same_full_scan_faults']
        and x['target_after_final_fault'] and x['injected_exception_evidence']
        for x in items)
    for key in ('requested_fault_events', 'matched_fault_events', 'applied_fault_events'):
        assert data[key] == sum(x[key] for x in items)
    union = coverage(valid_paths)
    assert 'error' not in union
    assert data['coverage_gain'] == max(0, union['total_branches']
                                        - data['healthy_coverage']['total_branches'])
    data['healthy_raw_evidence'] = trial_evidence(
        'healthy_final', data['healthy_elapsed_seconds'])
    data['source_audit'] = {
        'guard': 'HBaseFsck$3.visit line 2717 evaluates previous.getMetaEntry() == null after a non-null previous regionInfoMap entry.',
        'selected_throw': 'The else branch at line 2720 throws IOException("Two entries in hbase:meta are same ...") only if the previous entry already has a non-null meta entry.',
        'baseline_observation': 'The original test has three visitor/guard calls with null=true and no selected throw; expected UNDELETED_REPLICATION_QUEUE errors are separate.',
        'fault_contract': 'The case-local ServiceException wrapping the chosen IOException subclass is thrown at the server scanner-open RPC before that invocation returns a meta row. The original scanner retries; exact post-final-fault visitor markers and JUnit pass prove retained requests.',
        'result': 'No counted fault trial delivered the duplicate-entry branch: target throw line 2720 stayed uncovered; no exact target exception or unexpected target exception occurred.',
        'additional_io_audit': 'Three healthy fullScan invocations each had one target-before hasScan=true scanner-open RPC. The scoped probe saw no scan continuation, FileSystem.open, or FSDataInputStream.read* before target; this claim is limited to those APIs.'}
    assert not data['selected_exception_trials']
    assert not data['unexpected_target_exception_trials']
    assert all(not x['selected_exception_observed'] for x in items)
    data['selected_throw_line_2720_covered_after_fault'] = any(
        x['production_coverage'].get('target_lines', {}).get('2720', {})
        .get('instructions', 0) > 0 for x in items)
    data['instrumentation_provenance'] = {
        'counted_runtime': 'Unchanged original MiniHBaseCluster JUnit, case-local ByteBuddy and JaCoCo',
        'graphchecker_jar_used': False,
        'prewoven_classes_used': False,
        'region_skeletons_or_static_scope_map_read': False,
        'static_aggregate_or_closure_run': False,
        'original_test_modified': False,
        'request_identity': 'All ordered faults apply to the hbase:meta scan-open RPC inside one exact fullScanRegions invocation; a direct visitor guard marker follows the final fault before that invocation exits.'}
    data['source_revision'] = (HERE / 'source/revision.txt').read_text().strip()
    evidence = CASE / 'evidence'
    evidence.mkdir(exist_ok=True)
    files = [CASE / 'README.md', HERE / 'run.sh', HERE / 'campaign.py',
             HERE / 'finalize.py', HERE / 'src/HBase35Agent.java',
             HERE / 'src/NativeJUnit.java', HERE / 'src/CoverageReport.java',
             HERE / 'agent.jar', HERE / 'manifest.mf',
             HERE / 'audit/HBase35AuditAgent.java', HERE / 'audit/agent.jar',
             HERE / 'audit/manifest.mf',
             HERE / 'junit-platform-launcher-1.13.4.jar']
    files.extend(sorted((HERE / 'source').glob('*')))
    for item in items:
        files.extend(HERE / (item['id'] + suffix)
                     for suffix in ('.log', '.exec', '.exit'))
    for prefix in ('healthy', 'cal', 'agent_access_fail', 'campaign', 'audit'):
        files.extend(path for path in sorted(HERE.glob(prefix + '*'))
                     if path.is_file() and path.suffix in ('.log', '.exec', '.exit'))
    assert all(path.exists() for path in files)
    assert len(files) == len(set(files))
    data['evidence'].update({
        'readme': 'README.md', 'archive': 'evidence/hbase35-native-evidence.tar.gz',
        'manifest': 'evidence/native-manifest.json',
        'campaign_checkpoint': 'result.json',
        'trial_ledger': 'result.json#fault_trial_details',
        'trial_logs': 'native/r001.log through native/r%03d.log' % len(items),
        'trial_coverage': 'Matching native/rNNN.exec files',
        'io_audit_log': 'native/audit_read.log',
        'source_snapshot': 'native/source/ at HBase rel/2.6.6'})
    archive = evidence / 'hbase35-native-evidence.tar.gz'
    with tarfile.open(archive, 'w:gz') as out:
        for path in files:
            out.add(path, arcname=str(path.relative_to(CASE)))
    manifest = {'archive': str(archive.relative_to(CASE)),
                'archive_sha256': sha256(archive), 'file_count': len(files),
                'files': {str(path.relative_to(CASE)): sha256(path) for path in files}}
    (evidence / 'native-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    data['evidence']['archive_sha256'] = manifest['archive_sha256']
    save(data)


if __name__ == '__main__':
    main()
