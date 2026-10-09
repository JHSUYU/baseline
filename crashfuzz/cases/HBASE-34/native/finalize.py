#!/usr/bin/env python3
"""Reparse the HBASE-34 native ledger and package case-only evidence."""
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
    assert data['healthy_target_guard_line_159_covered']
    assert not data['healthy_target_throw_line_160_covered']
    items = data['fault_trial_details']
    assert data['fault_trials'] == len(items)
    assert len({item['plan'] for item in items}) == len(items)
    valid_paths = [HERE / 'healthy_ident.exec']
    for item in items:
        fresh = parse(item['id'], item['plan'])
        raw = (HERE / (item['id'] + '.log')).read_text(errors='replace')
        for key in ('requested_fault_events', 'matched_fault_events',
                    'applied_fault_events', 'applied_selector_sequence',
                    'strict', 'same_logical_whoami_request',
                    'selected_exception_observed', 'junit_passed', 'junit_exit'):
            assert fresh[key] == item[key], (item['id'], key, fresh[key], item[key])
        assert len(item['plan'].split(',')) <= data['fault_budget']['max_faults_per_trial']
        for event in item['observed_io']:
            if event['applied']:
                assert 'HBASE34 injected SASL_IN hit=%d' % event['hit'] in raw, (
                    item['id'], event['hit'])
        exe = HERE / (item['id'] + '.exec')
        assert exe.exists(), exe
        if item['strict'] and item['same_logical_whoami_request'] and item['target_after_final_fault']:
            assert fresh['target_after_final_fault']
            assert item['production_coverage']['target_lines']['159']['instructions'] > 0
            valid_paths.append(exe)
    assert data['strict_injections'] == sum(item['strict'] for item in items)
    assert data['target_after_fault'] == sum(
        item['strict'] and item['same_logical_whoami_request']
        and item['target_after_final_fault'] for item in items)
    assert data['requested_fault_events'] == sum(item['requested_fault_events'] for item in items)
    assert data['matched_fault_events'] == sum(item['matched_fault_events'] for item in items)
    assert data['applied_fault_events'] == sum(item['applied_fault_events'] for item in items)
    union = coverage(valid_paths)
    assert 'error' not in union
    assert data['coverage_gain'] == (union['total_branches']
                                    - data['healthy_coverage']['total_branches'])
    data['selected_throw_line_160_covered_after_fault'] = any(
        item['production_coverage'].get('target_lines', {}).get('160', {})
        .get('instructions', 0) > 0 for item in items)
    data['instrumentation_provenance'] = {
        'counted_runtime': 'Unchanged original SecureTestCluster JUnit, case-local ByteBuddy and JaCoCo',
        'graphchecker_jar_used': False,
        'prewoven_classes_used': False,
        'region_skeletons_or_static_scope_map_read': False,
        'static_aggregate_or_closure_run': False,
        'original_test_modified': False,
        'test_utility_compensation': 'Original KeyStoreTestUtil source was compiled case-locally with a JAR-resource path fallback for SSL files; the selected production target and JUnit test code were not changed.',
        'request_identity': 'Each applied fault lies inside the sole testToken invocation; one whoAmI service dispatch and a post-final-fault retrievePassword call with token key ID 1 occur in that same original test body.'}
    data['source_revision'] = (HERE / 'source/revision.txt').read_text().strip()
    evidence = CASE / 'evidence'
    evidence.mkdir(exist_ok=True)
    files = [CASE / 'README.md', HERE / 'run.sh', HERE / 'campaign.py',
             HERE / 'finalize.py', HERE / 'src/HBase34Agent.java',
             HERE / 'src/NativeJUnit.java', HERE / 'src/CoverageReport.java',
             HERE / 'src/org/apache/hadoop/hbase/http/ssl/KeyStoreTestUtil.java',
             HERE / 'source/revision.txt',
             HERE / 'source/AuthenticationTokenSecretManager.java',
             HERE / 'source/TestGenerateDelegationToken.java',
             HERE / 'source/SecureTestCluster.java',
             HERE / 'source/DigestSaslServerAuthenticationProvider.java',
             HERE / 'source/KeyStoreTestUtil.java', HERE / 'agent.jar',
             HERE / 'manifest.mf', HERE / 'junit-platform-launcher-1.13.4.jar']
    for item in items:
        for suffix in ('.log', '.exec', '.exit'):
            files.append(HERE / (item['id'] + suffix))
    for name in ('healthy', 'healthy_fixed', 'healthy_bc', 'healthy_ssl',
                 'healthy_ctx', 'healthy_diag', 'healthy_jarfix', 'healthy_io',
                 'healthy_counted', 'healthy_ident', 'cal1', 'cal2', 'campaign'):
        files.extend(path for suffix in ('.log', '.exec', '.exit')
                     if (path := HERE / (name + suffix)).exists())
    assert all(path.exists() for path in files)
    data['evidence'].update({
        'readme': 'README.md', 'archive': 'evidence/hbase34-native-evidence.tar.gz',
        'manifest': 'evidence/native-manifest.json',
        'trial_logs': 'native/r001.log through native/r%03d.log' % len(items),
        'trial_coverage': 'Matching native/rNNN.exec files',
        'source_snapshot': 'native/source/ at HBase rel/2.6.6'})
    archive = evidence / 'hbase34-native-evidence.tar.gz'
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
