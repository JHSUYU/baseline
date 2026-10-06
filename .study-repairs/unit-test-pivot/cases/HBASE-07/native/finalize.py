#!/usr/bin/env python3
"""Reparse the original-JUnit ledger and package immutable case evidence."""
import hashlib
import json
from pathlib import Path
import tarfile

from campaign import CASE, HERE, RESULT, coverage, parse, save


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    data = json.loads(RESULT.read_text())
    assert data['status'] in ('quality_complete', 'candidate_review')
    assert data['healthy_junit_passed'] and data['healthy_target_guard_count'] == 1
    assert data['healthy_guard_values'] == [True]
    assert data['healthy_observed_io_doors'] == ['MASTER', 'EXISTS', 'CHECK', 'STATE']
    items = data['fault_trial_details']
    assert data['fault_trials'] == len(items)
    assert len({x['plan'] for x in items}) == len(items)
    valid_paths = [HERE / 'healthy_final.exec']
    for old in items:
        fresh = parse(old['id'], old['plan'])
        for key in ('requested_fault_events', 'matched_fault_events', 'applied_fault_events',
                    'applied_selector_sequence', 'strict', 'target_after_final_fault',
                    'target_exception_observed', 'junit_passed', 'junit_exit'):
            assert fresh[key] == old[key], (old['id'], key, fresh[key], old[key])
        assert len(old['plan'].split(',')) <= data['fault_budget']['max_faults_per_trial']
        exe = HERE / (old['id'] + '.exec')
        assert exe.exists(), exe
        if old['strict'] and old['target_after_final_fault']:
            valid_paths.append(exe)
    union = coverage(valid_paths)
    assert 'error' not in union
    assert data['coverage_gain'] == union['total_branches'] - data['healthy_coverage']['total_branches']
    assert data['strict_injections'] == sum(x['strict'] for x in items)
    assert data['target_after_fault'] == sum(x['strict'] and x['target_after_final_fault'] for x in items)
    data['selected_throw_line_2788_covered'] = any(
        x['production_coverage'].get('target_lines', {}).get('2788', {}).get('instructions', 0) > 0
        for x in items)
    data['instrumentation_provenance'] = {
        'counted_runtime': 'Unchanged original JUnit, case-local ByteBuddy, JaCoCo',
        'graphchecker_jar_used': False, 'prewoven_classes_used': False,
        'region_skeletons_or_static_scope_map_read': False,
        'static_aggregate_or_closure_run': False,
        'original_test_modified': False,
        'exploratory_healthy_note': 'First uncounted healthy JUnit passed but JVM lingered; '
                                    'case-local launcher explicitly exits after JUnit summary.'}
    evidence = CASE / 'evidence'
    evidence.mkdir(exist_ok=True)
    files = [CASE / 'README.md', HERE / 'run.sh', HERE / 'campaign.py',
             HERE / 'finalize.py', HERE / 'src' / 'HBase07Agent.java',
             HERE / 'src' / 'NativeJUnit.java', HERE / 'src' / 'CoverageReport.java',
             HERE / 'original-mapping-result.json', HERE / 'agent.jar', HERE / 'manifest.mf',
             HERE / 'junit-platform-launcher-1.13.4.jar', HERE / 'healthy_final.log',
             HERE / 'healthy_final.exec', HERE / 'healthy_final.exit']
    for item in items:
        for suffix in ('.log', '.exec', '.exit'):
            files.append(HERE / (item['id'] + suffix))
    assert all(path.exists() for path in files)
    files.extend(path for path in [HERE / 'healthy.log', HERE / 'healthy.exec',
                                  HERE / 'healthy.exit', HERE / 'campaign.log',
                                  HERE / 'campaign.exit'] if path.exists())
    data['evidence'].update({'readme': 'README.md', 'archive':
                             'evidence/hbase07-native-evidence.tar.gz',
                             'manifest': 'evidence/native-manifest.json',
                             'trial_logs': 'native/r001.log through native/r%03d.log'
                                           % data['fault_trials'],
                             'trial_coverage': 'Matching native/rNNN.exec files'})
    save(data)
    archive = evidence / 'hbase07-native-evidence.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(CASE)))
    manifest = {'archive': str(archive.relative_to(CASE)),
                'archive_sha256': digest(archive), 'file_count': len(files),
                'files': {str(path.relative_to(CASE)): digest(path) for path in files}}
    (evidence / 'native-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    data['evidence']['archive_sha256'] = manifest['archive_sha256']
    save(data)


if __name__ == '__main__':
    main()
