#!/usr/bin/env python3
"""Run an original SolrCloud backup stress JUnit with the independent SOLR-22 probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from build import HERE, CASE, JAVA8, original_classpath
from window_recount import recount


SOURCE = HERE / 'solr-pristine'
TESTS = {
    'testReplicationHandler': (
        'org.apache.solr.handler.TestStressThreadBackup',
        ['org/apache/solr/handler/BackupStatusChecker.java']),
    'testCoreAdminHandler': (
        'org.apache.solr.handler.TestStressThreadBackup',
        ['org/apache/solr/handler/BackupStatusChecker.java']),
    'testSnapshots': (
        'org.apache.solr.core.snapshots.TestSolrCloudSnapshots',
        ['org/apache/solr/handler/BackupRestoreUtils.java']),
}


def smoke(method: str) -> dict:
    if method not in TESTS:
        raise ValueError('unknown original cluster JUnit method')
    test_class, helper_names = TESTS[method]
    source_root = SOURCE / 'solr/core/src/test'
    test_source = source_root / (test_class.replace('.', '/') + '.java')
    helpers = [source_root / name for name in helper_names]
    out = HERE / 'supplemental' / method
    if (out / 'run.json').is_file():
        return json.loads((out / 'run.json').read_text())
    out.mkdir(parents=True, exist_ok=True)
    classes = out / 'classes'
    classes.mkdir(exist_ok=True)
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', original_classpath(), '-d', str(classes),
                    *(str(helper) for helper in helpers), str(test_source)],
                   check=True, capture_output=True, text=True)
    test_class_file = classes / (test_class.replace('.', '/') + '.class')
    scratch = out / 'scratch'
    scratch.mkdir(exist_ok=True)
    cp = ':'.join((str(classes), str(HERE / 'classes'), original_classpath()))
    command = [
        str(JAVA8 / 'java'), '-ea', '-Xmx3g',
        '-javaagent:' + str(CASE / 'v5/lib/jacoco-agent.jar')
        + '=destfile=' + str(out / 'jacoco.exec')
        + ',append=false,dumponexit=true,includes=org.apache.solr.*:org.apache.lucene.*',
        '-javaagent:' + str(HERE / 'solr22-independent-agent.jar'),
        '-Dsolr22.trace.file=' + str(out / 'events.jsonl'),
        '-Djava.awt.headless=true',
        '-Djava.io.tmpdir=' + str(scratch),
        '-DtempDir=' + str(scratch),
        '-Dtests.seed=F0993D5343E20BA4',
        '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
        '-Dcommon.dir=' + str(SOURCE / 'lucene'),
        '-Dtests.asserts=true', '-Dtests.slow=true', '-Dtests.nightly=true',
        '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
        '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
        '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
        '-Djdk.map.althashing.threshold=0',
        '-Djava.security.egd=file:/dev/./urandom',
        '-cp', cp, 'research.solr22.OriginalJUnit', test_class, method,
    ]
    started = time.monotonic()
    with (out / 'console.log').open('w') as console:
        try:
            process = subprocess.run(command, cwd=SOURCE, stdout=console,
                                     stderr=subprocess.STDOUT, timeout=900,
                                     env=os.environ.copy(), check=False)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    counts: dict[str, int] = {}
    trace_error = None
    window = {}
    events_file = out / 'events.jsonl'
    if events_file.is_file():
        try:
            for line in events_file.open():
                if line.strip():
                    event = json.loads(line)['event']
                    counts[event] = counts.get(event, 0) + 1
            window = recount(events_file)
        except (OSError, ValueError) as failure:
            trace_error = str(failure)
    report = {
        'case_id': 'SOLR-22', 'methodology': 'independent_asm_original_cluster_junit_healthy',
        'original_test': test_class + '#' + method,
        'original_test_source_sha256': hashlib.sha256(test_source.read_bytes()).hexdigest(),
        'original_test_class_sha256': hashlib.sha256(test_class_file.read_bytes()).hexdigest(),
        'agent_sha256': hashlib.sha256((HERE / 'solr22-independent-agent.jar').read_bytes()).hexdigest(),
        'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
        'original_source_revision': subprocess.check_output(
            ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'exit_code': exit_code,
        'target_checks': counts.get('TARGET_CHECK', 0),
        'target_throws': counts.get('TARGET_THROW', 0),
        'directory_io': counts.get('FAULT_POINT_OBSERVED', 0),
        'onCommit_windows': counts.get('ONCOMMIT_WINDOW_START', 0),
        'same_writer_io_in_onCommit_window': window.get('directory_io_in_complete_windows'),
        'same_policy_target_checks_in_onCommit_window': window.get('target_checks_in_complete_windows'),
        'trace_parse_error': trace_error,
        'trace': str(events_file),
        'junit_console': str(out / 'console.log'),
    }
    (out / 'run.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('method', choices=sorted(TESTS))
    args = parser.parse_args()
    print(json.dumps(smoke(args.method), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
