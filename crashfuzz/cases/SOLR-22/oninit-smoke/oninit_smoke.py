#!/usr/bin/env python3
"""Healthy original TestPullReplica JUnit with an isolated onInit interval probe."""

from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
INDEPENDENT = HERE.parent / 'independent'
sys.path.insert(0, str(INDEPENDENT))
from build import CASE, JAVA8, original_classpath  # noqa: E402

SOURCE = INDEPENDENT / 'solr-pristine'
TEST_SOURCE = SOURCE / 'solr/core/src/test/org/apache/solr/cloud/TestPullReplica.java'
TEST_CLASS = 'org.apache.solr.cloud.TestPullReplica'
ALLOWED_METHODS = ('testKillPullReplica', 'testAddDocs')


def build() -> Path:
    classes = HERE / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    original = INDEPENDENT / 'src/research/solr22'
    overlay = HERE / 'build-src/research/solr22'
    overlay.mkdir(parents=True, exist_ok=True)
    for name in ('Agent.java', 'Probe.java'):
        shutil.copy2(original / name, overlay / name)
    subprocess.run(['patch', '--batch', '-p0', '-d', str(overlay)],
                   input=(HERE / 'oninit-agent.patch').read_text(),
                   capture_output=True, text=True, check=True)
    java = sorted(overlay.glob('*.java'))
    cp = ':'.join((str(INDEPENDENT / 'classes'), original_classpath(),
                   str(CASE / 'v5/lib/jacoco-core.jar')))
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', cp, '-d', str(classes), *(str(path) for path in java)],
                   check=True, capture_output=True, text=True)
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solr22.Agent\n\n')
    agent = HERE / 'solr22-oninit-smoke-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), '.'], check=True)
    return agent


def recount(events: list[dict]) -> dict:
    active: dict[tuple[int, str], dict] = {}
    complete: list[dict] = []
    incomplete: list[dict] = []
    for event in events:
        kind = event['event']
        key = (event['threadId'], event.get('policyId'))
        if kind == 'ONINIT_WINDOW_START':
            if key in active:
                incomplete.append(active.pop(key))
            active[key] = {'start': event['seq'], 'threadId': key[0],
                           'policyId': key[1], 'sourceKey': event.get('sourceKey'),
                           'directory_io': [], 'target_checks': []}
        elif kind in ('ONINIT_WINDOW_END', 'ONINIT_RETURN'):
            window = active.pop(key, None)
            if window is not None:
                window['end'] = event['seq']
                (complete if kind == 'ONINIT_WINDOW_END' else incomplete).append(window)
        elif kind == 'FAULT_POINT_OBSERVED':
            for (thread, _), window in active.items():
                if thread == event['threadId']:
                    window['directory_io'].append(event['seq'])
        elif kind == 'TARGET_CHECK':
            for (_, policy), window in active.items():
                if policy is not None and policy == event.get('policyId'):
                    window['target_checks'].append(event['seq'])
    incomplete.extend(active.values())
    return {
        'complete_onInit_windows': len(complete),
        'incomplete_onInit_windows': len(incomplete),
        'same_writer_directory_io_in_complete_windows': sum(
            len(window['directory_io']) for window in complete),
        'same_policy_target_checks_in_complete_windows': sum(
            len(window['target_checks']) for window in complete),
        'unresolved_complete_windows': sum(
            str(window['sourceKey']).startswith('UNRESOLVED:') for window in complete),
        'windows_with_io_or_target': [window for window in complete
                                     if window['directory_io'] or window['target_checks']],
    }


def main(method: str) -> None:
    agent = build()
    out = HERE / method
    out.mkdir(parents=True, exist_ok=True)
    frozen_agent = out / 'agent.jar'
    shutil.copy2(agent, frozen_agent)
    scratch = out / 'scratch'
    scratch.mkdir(exist_ok=True)
    cp = ':'.join((str(HERE / 'classes'), str(INDEPENDENT / 'classes'),
                   original_classpath()))
    command = [
        str(JAVA8 / 'java'), '-ea', '-Xmx3g',
        '-javaagent:' + str(frozen_agent),
        '-Dsolr22.trace.file=' + str(out / 'events.jsonl'),
        '-Djava.awt.headless=true', '-Djava.io.tmpdir=' + str(scratch),
        '-DtempDir=' + str(scratch), '-Dtests.seed=F0993D5343E20BA4',
        '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
        '-Dcommon.dir=' + str(SOURCE / 'lucene'),
        '-Dtests.asserts=true', '-Dtests.slow=true', '-Dtests.nightly=false',
        '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
        '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
        '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
        '-Djdk.map.althashing.threshold=0',
        '-Djava.security.egd=file:/dev/./urandom',
        '-cp', cp, 'research.solr22.OriginalJUnit', TEST_CLASS, method,
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
    events = [json.loads(line) for line in (out / 'events.jsonl').open()
              if line.strip()] if (out / 'events.jsonl').is_file() else []
    counts = Counter(event['event'] for event in events)
    log = (out / 'console.log').read_text()
    gate = re.search(r'SOLR22_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', log)
    report = {
        'case_id': 'SOLR-22',
        'methodology': 'original_cluster_junit_onInit_healthy_smoke_no_fault',
        'test': TEST_CLASS + '#' + method,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'exit_code': exit_code,
        'junit_gate': [int(x) for x in gate.groups()] if gate else None,
        'source_revision': subprocess.check_output(
            ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
        'original_test_source_sha256': hashlib.sha256(TEST_SOURCE.read_bytes()).hexdigest(),
        'agent_sha256': hashlib.sha256(frozen_agent.read_bytes()).hexdigest(),
        'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
        'target_checks': counts['TARGET_CHECK'],
        'exact_target_throws': counts['TARGET_THROW'],
        'directory_io_observed': counts['FAULT_POINT_OBSERVED'],
        'onInit_window_starts': counts['ONINIT_WINDOW_START'],
        'onCommit_window_starts': counts['ONCOMMIT_WINDOW_START'],
        'onInit_window_audit': recount(events),
        'trace': str(out / 'events.jsonl'),
    }
    (out / 'run.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: report[key] for key in ('test', 'elapsed_seconds',
          'exit_code', 'junit_gate', 'target_checks', 'exact_target_throws',
          'directory_io_observed', 'onInit_window_starts',
          'onCommit_window_starts')}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('method', choices=ALLOWED_METHODS)
    main(parser.parse_args().method)
