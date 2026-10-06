#!/usr/bin/env python3
"""Reparse shared unchanged-JUnit evidence and package three case results."""
import hashlib
import json
from pathlib import Path
import tarfile

from campaign import CASES, EXPECTED, HERE, ROOT, THROW_LINES, case_path, coverage, parse, save


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    data = {n: json.loads((case_path(n) / 'result.json').read_text()) for n in CASES}
    assert len({d['fault_trials'] for d in data.values()}) == 1
    count = data[13]['fault_trials']
    assert all(d['status'] in ('quality_complete', 'candidate_review') for d in data.values())
    assert all(d['healthy_junit_passed'] and d['healthy_target_guard_count'] == 2
               for d in data.values())
    assert all(d['healthy_observed_io_doors'] ==
               ['META', 'REGION_INFO', 'META', 'REGION_INFO'] for d in data.values())
    for n in CASES:
        items = data[n]['fault_trial_details']
        assert len(items) == count and len({x['plan'] for x in items}) == count
        valid = [HERE / 'healthy_v2.exec']
        for item in items:
            fresh = parse(item['id'], item['plan'])
            for key in ('requested_fault_events', 'matched_fault_events',
                        'applied_fault_events', 'applied_selector_sequence', 'strict',
                        'junit_passed', 'junit_exit', 'elapsed_seconds'):
                assert item[key] == fresh[key], (n, item['id'], key)
            assert item['target_after_final_fault'] == fresh['target_after_final_fault'][n]
            assert item['selected_guard_failure'] == fresh['selected_guard_failure'][n]
            assert item['post_fault_checks'] == fresh['post_fault_checks'][n]
            assert len(item['plan'].split(',')) <= data[n]['fault_budget']['max_faults_per_trial']
            exe = HERE / (item['id'] + '.exec')
            assert exe.exists(), exe
            if item['strict'] and item['target_after_final_fault']:
                valid.append(exe)
            if item['selected_guard_failure']:
                assert item['strict'] and item['target_after_final_fault']
                assert any(EXPECTED[n] in x['exception'] for x in item['prepare_exits'])
                assert item['production_coverage']['target_lines'][str(THROW_LINES[n])][
                    'instructions'] > 0
        union = coverage(valid)
        assert 'error' not in union
        assert data[n]['coverage_gain'] == union['total_branches'] - data[n][
            'healthy_coverage']['total_branches']
        assert data[n]['strict_injections'] == sum(x['strict'] for x in items)
        assert data[n]['target_after_fault'] == sum(x['strict'] and x[
            'target_after_final_fault'] for x in items)
        assert data[n]['selected_target_exception_trials'] == sum(
            x['strict'] and x['target_after_final_fault'] and x['selected_guard_failure']
            for x in items)
        data[n]['selected_throw_line_covered'] = any(
            x['production_coverage'].get('target_lines', {}).get(
                str(THROW_LINES[n]), {}).get('instructions', 0) > 0 for x in items)
        data[n]['instrumentation_provenance'] = {
            'counted_runtime': 'Unchanged original JUnit, case-local ByteBuddy and JaCoCo',
            'graphchecker_jar_used': False, 'prewoven_classes_used': False,
            'region_skeletons_or_static_scope_map_read': False,
            'static_aggregate_or_closure_run': False,
            'original_test_modified': False,
            'uncounted_startup_note': 'Initial probe used non-public advice members; repaired before healthy baseline.',
            'uncounted_calibration_note': 'META one-fault and eight-fault calibrations used probe v1; not in new campaign budget.',
            'uncounted_region_info_note': 'REGION_INFO fault reaches no selected check after the fault and fails original JUnit.'}
    evidence_dir = case_path(13) / 'evidence'
    evidence_dir.mkdir(exist_ok=True)
    files = [case_path(n) / 'README.md' for n in CASES]
    files += [HERE / name for name in (
        'run.sh', 'campaign.py', 'finalize.py', 'write_readmes.py', 'src/HBase1315Agent.java',
        'src/HBase1315Agent-calibration-v1.java', 'src/NativeJUnit.java',
        'src/CoverageReport.java', 'agent.jar', 'agent-calibration-v1.jar',
        'manifest.mf', 'junit-platform-launcher-1.13.4.jar',
        'original-mapping-results.json', 'healthy_final.log', 'healthy_final.exec',
        'healthy_final.exit', 'healthy_v2.log', 'healthy_v2.exec', 'healthy_v2.exit',
        'calibrate01.log', 'calibrate01.exec', 'calibrate01.exit',
        'calibrate08.log', 'calibrate08.exec', 'calibrate08.exit',
        'region_probe.log', 'region_probe.exec', 'region_probe.exit',
        'campaign.log', 'campaign.exit')]
    for i in range(1, count + 1):
        for suffix in ('.log', '.exec', '.exit'):
            files.append(HERE / ('r%03d' % i + suffix))
    files.extend(path for path in [HERE / 'healthy.log', HERE / 'healthy.exec',
                                   HERE / 'healthy.exit'] if path.exists())
    assert all(path.exists() for path in files)
    for n in CASES:
        data[n]['evidence'].update({
            'readme': 'README.md',
            'shared_archive': '../HBASE-13/evidence/hbase13-15-native-evidence.tar.gz',
            'shared_manifest': '../HBASE-13/evidence/native-manifest.json',
            'trial_logs': '../HBASE-13/native/r001.log through r%03d.log' % count,
            'trial_coverage': 'Matching ../HBASE-13/native/rNNN.exec files'})
        save(n, data[n])
    archive = evidence_dir / 'hbase13-15-native-evidence.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(ROOT)))
    manifest = {'archive': str(archive.relative_to(ROOT)),
                'archive_sha256': digest(archive), 'file_count': len(files),
                'files': {str(path.relative_to(ROOT)): digest(path) for path in files}}
    (evidence_dir / 'native-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for n in CASES:
        data[n]['evidence']['archive_sha256'] = manifest['archive_sha256']
        save(n, data[n])


if __name__ == '__main__':
    main()
