#!/usr/bin/env python3
"""Audit the case-only ledger and package compact, source-linked evidence."""
import hashlib
import json
from pathlib import Path
import tarfile

from campaign import CASE, HERE, RESULT, coverage, parse, save


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    data = json.loads(RESULT.read_text())
    assert data['status'] in ('quality_complete', 'candidate_review')
    assert data['fault_trials'] == len(data['fault_trial_details'])
    assert len({x['plan'] for x in data['fault_trial_details']}) == data['fault_trials']
    assert data['healthy_junit_passed'] and data['healthy_target_guard_count'] == 1
    assert data['healthy_guard_values'] == [False]
    valid_paths = [HERE / 'healthy_final.exec']
    for old in data['fault_trial_details']:
        fresh = parse(old['id'], old['plan'])
        for key in ('requested_fault_events', 'matched_fault_events', 'applied_fault_events',
                    'strict', 'target_after_final_fault', 'target_exception_observed',
                    'junit_passed', 'junit_exit'):
            assert fresh[key] == old[key], (old['id'], key, fresh[key], old[key])
        assert len(old['plan'].split(',')) <= data['fault_budget']['max_faults_per_trial']
        path = HERE / (old['id'] + '.exec')
        assert path.exists(), path
        if old['strict'] and old['target_after_final_fault']:
            valid_paths.append(path)
    assert data['strict_injections'] == sum(x['strict'] for x in data['fault_trial_details'])
    assert data['target_after_fault'] == sum(
        x['target_after_final_fault'] for x in data['fault_trial_details'])
    branch_union = coverage(valid_paths)['total_branches']
    assert data['coverage_gain'] == branch_union - data['healthy_coverage']['total_branches']
    data['fatal_target_trials'] = sum(x['target_exception_observed']
                                      and x['target_after_final_fault']
                                      for x in data['fault_trial_details'])
    data['selected_throw_line_1105_covered'] = any(
        x['production_coverage'].get('target_lines', {}).get('1105', {}).get('instructions', 0) > 0
        for x in data['fault_trial_details'])
    data['instrumentation_provenance'] = {
        'counted_runtime': 'Native JUnit Platform launcher, case-local ByteBuddy agent, JaCoCo',
        'graphchecker_jar_used': False, 'prewoven_classes_used': False,
        'region_skeletons_or_static_scope_map_read': False,
        'static_aggregate_or_closure_run': False,
        'original_test_modified': False,
        'legacy_graphchecker_trial_count_excluded': 3}
    evidence = CASE / 'evidence'
    evidence.mkdir(exist_ok=True)
    files = [CASE / 'README.md',
             HERE / 'run.sh', HERE / 'campaign.py', HERE / 'prefetch_55_64.py',
             HERE / 'prefetch_65_80.py',
             HERE / 'finalize.py',
             HERE / 'src' / 'HBase01Agent.java', HERE / 'src' / 'NativeJUnit.java',
             HERE / 'src' / 'CoverageReport.java',
             HERE / 'agent.jar', HERE / 'manifest.mf',
             HERE / 'junit-platform-launcher-1.13.4.jar',
             HERE / 'legacy-origin.json', HERE / 'legacy-graphchecker-result.json',
             HERE / 'legacy-graphchecker-README.md',
             HERE / 'healthy_final.log', HERE / 'healthy_final.exec',
             HERE / 'healthy_final.exit']
    for item in data['fault_trial_details']:
        for suffix in ('.log', '.exec', '.exit'):
            files.append(HERE / (item['id'] + suffix))
    assert all(path.exists() for path in files)
    files.extend(path for path in [
        HERE / 'healthy.log', HERE / 'healthy.exec', HERE / 'healthy.exit',
        HERE / 'campaign.log', HERE / 'campaign.exit',
        HERE / 'resume.log', HERE / 'resume.exit',
        HERE / 'prefetch.log', HERE / 'prefetch.exit',
        HERE / 'prefetch2.log', HERE / 'prefetch2.exit',
        HERE / 'prefetch3.log', HERE / 'prefetch3.exit'] if path.exists())
    archive = evidence / 'hbase01-native-evidence.tar.gz'
    data['evidence'].update({'archive': 'evidence/hbase01-native-evidence.tar.gz',
                             'manifest': 'evidence/native-manifest.json',
                             'trial_logs': 'native/r001.log through native/r%03d.log'
                                           % data['fault_trials'],
                             'trial_coverage': 'Matching native/rNNN.exec files',
                             'legacy_archive': 'evidence/hbase01-evidence.tar.gz'})
    save(data)
    with tarfile.open(archive, 'w:gz') as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(CASE)))
    manifest = {'archive': str(archive.relative_to(CASE)),
                'archive_sha256': digest(archive),
                'file_count': len(files),
                'files': {str(path.relative_to(CASE)): digest(path) for path in files}}
    (evidence / 'native-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    data['evidence']['archive_sha256'] = manifest['archive_sha256']
    save(data)


if __name__ == '__main__':
    main()
