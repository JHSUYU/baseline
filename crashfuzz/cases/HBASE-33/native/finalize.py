#!/usr/bin/env python3
"""Verify HBASE-33 healthy target reachability and package isolated evidence."""
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    log = (HERE / 'healthy_fixed.log').read_text(errors='replace')
    assert (HERE / 'healthy_fixed.exit').read_text().strip() == '0'
    assert log.count('HBASE33 TEST_ENTER method=testTokenCreation') == 2
    assert log.count('HBASE33 TEST_EXIT exception=none') == 2
    assert log.count('HBASE33 TARGET_ENTER keyId=1 keyPresent=true') == 2
    assert log.count('HBASE33 TARGET_EXIT exception=none') == 2
    assert 'HBASE33 JUNIT found=2 succeeded=2 failed=0 aborted=0' in log
    elapsed = float(re.search(r'ELAPSED_SECONDS=([\d.]+)', log)[1])
    report = subprocess.run(['bash', str(HERE / 'run.sh'), 'coverage', 'healthy_fixed'],
                            capture_output=True, text=True, check=True).stdout
    lines = {int(number): {'instructions': int(ins), 'branches': int(branches)}
             for number, ins, branches in re.findall(
                 r'COVERAGE line=(\d+) instructions=(\d+) branches=(\d+)', report)}
    assert lines[138]['instructions'] > 0
    assert lines[139]['instructions'] == 0
    assert lines[141]['instructions'] == 0
    assert lines[159]['instructions'] > 0
    assert lines[160]['instructions'] == 0
    setup_log = (HERE / 'healthy.log').read_text(errors='replace')
    assert 'java.lang.IllegalAccessError' in setup_log
    assert 'HBASE33 JUNIT found=2 succeeded=0 failed=2 aborted=0' in setup_log

    data = json.loads(RESULT.read_text())
    data.update({
        'status': 'no_cluster_test',
        'target_reached': False,
        'target_method_entered': True,
        'target_method_entry_count': 2,
        'healthy_guard_line_139_reached': False,
        'healthy_throw_line_141_reached': False,
        'healthy_junit_passed': True,
        'healthy_junit_found': 2,
        'healthy_junit_succeeded': 2,
        'healthy_key_present_at_both_entries': True,
        'healthy_key_id': 1,
        'healthy_coverage_target_lines': lines,
        'elapsed_seconds': elapsed,
        'fault_trials': 0,
        'strict_injections': 0,
        'target_after_fault': 0,
        'coverage_gain': 0,
        'bug_mark': 'none',
        'stop_reason': ('The original mapped JUnit enters retrievePassword with the key '
                        'present in both parameterizations, so nested abort guard line 139 '
                        'is not executed; the test uses MiniZK and TokenServer rather than '
                        'MiniHBaseCluster. No original cluster test was found for missing '
                        'key plus aborted watcher.'),
        'instrumentation_provenance': {
            'counted_runtime': 'Unchanged original JUnit, case-local ByteBuddy and JaCoCo',
            'graphchecker_jar_used': False,
            'prewoven_classes_used': False,
            'region_skeletons_or_static_scope_map_read': False,
            'original_test_modified': False,
            'setup_failure_counted_as_healthy': False},
        'source_revision': (HERE / 'source/revision.txt').read_text().strip(),
        'evidence': {
            'readme': 'README.md',
            'healthy_log': 'native/healthy_fixed.log',
            'healthy_exec': 'native/healthy_fixed.exec',
            'setup_failure_log': 'native/healthy.log',
            'archive': 'evidence/hbase33-healthy-reachability.tar.gz',
            'manifest': 'evidence/native-manifest.json'}})
    files = [CASE / 'README.md', HERE / 'run.sh', HERE / 'finalize.py',
             HERE / 'src/HBase33Agent.java', HERE / 'src/NativeJUnit.java',
             HERE / 'src/CoverageReport.java', HERE / 'source/revision.txt',
             HERE / 'source/AuthenticationTokenSecretManager.java',
             HERE / 'source/TestTokenAuthentication.java', HERE / 'agent.jar',
             HERE / 'manifest.mf', HERE / 'junit-platform-launcher-1.13.4.jar']
    for suffix in ('.log', '.exec', '.exit'):
        files.append(HERE / ('healthy' + suffix))
        files.append(HERE / ('healthy_fixed' + suffix))
    assert all(path.exists() for path in files)
    evidence = CASE / 'evidence'
    evidence.mkdir(exist_ok=True)
    archive = evidence / 'hbase33-healthy-reachability.tar.gz'
    with tarfile.open(archive, 'w:gz') as out:
        for path in files:
            out.add(path, arcname=str(path.relative_to(CASE)))
    manifest = {'archive': str(archive.relative_to(CASE)),
                'archive_sha256': sha256(archive), 'file_count': len(files),
                'files': {str(path.relative_to(CASE)): sha256(path) for path in files}}
    (evidence / 'native-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    data['evidence']['archive_sha256'] = manifest['archive_sha256']
    RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
