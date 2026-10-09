#!/usr/bin/env python3
"""Verify new-budget runner and probe have no GraphChecker/skeleton dependency."""

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import campaign


HERE = Path(__file__).resolve().parent
RUNS = Path('/users/ZhenyuLi/zk04-runs')
REPORT = Path('/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml')
RUNNER = HERE / 'runner/original-junit-runner.jar'
AGENT = HERE / 'agent/audit-agent.jar'
FORBIDDEN = (b'graphchecker', b'skeleton')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jar_has_forbidden(path):
    with zipfile.ZipFile(path) as archive:
        return sorted(name for name in archive.namelist()
                      if name.endswith('.class') and any(
                          word in archive.read(name).lower() for word in FORBIDDEN))


def main():
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    surefire_cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    actual_cp_checks = {}
    for run_id in ('budget5-01b', 'budget6-01', 'budget7-01', 'budget8-01'):
        log = (RUNS / run_id / 'junit.log').read_text(errors='replace')
        cp_lines = [line for line in log.splitlines()
                    if 'Server environment:java.class.path=' in line]
        if len(cp_lines) != 1:
            raise RuntimeError('{}: expected one actual classpath log'.format(run_id))
        actual = cp_lines[0].split('Server environment:java.class.path=', 1)[1]
        actual_cp_checks[run_id] = {
            'logged_classpath_sha256': hashlib.sha256(actual.encode()).hexdigest(),
            'graphchecker_present': 'graphchecker' in actual.lower(),
            'skeleton_present': 'skeleton' in actual.lower(),
            'plain_runner_present': 'original-junit-runner.jar' in actual,
        }
    agent_sources = list((HERE / 'agent/src').rglob('*.java'))
    runner_sources = list((HERE / 'runner/src').rglob('*.java'))
    source_violations = sorted(str(path) for path in agent_sources + runner_sources
                               if any(word in path.read_bytes().lower() for word in FORBIDDEN))
    jar_violations = {str(path): jar_has_forbidden(path) for path in (AGENT, RUNNER)}
    output = {
        'source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
        'original_test': 'org.apache.zookeeper.server.ConnectionMetricsTest#testRevalidateCount',
        'agent_sha256': sha(AGENT),
        'runner_sha256': sha(RUNNER),
        'surefire_classpath_graphchecker_present': 'graphchecker' in surefire_cp.lower(),
        'surefire_classpath_skeleton_present': 'skeleton' in surefire_cp.lower(),
        'actual_jvm_classpaths': actual_cp_checks,
        'agent_and_runner_source_violations': source_violations,
        'agent_and_runner_class_violations': jar_violations,
        'historical_runner_limit': 'The earlier 25 attempts loaded a legacy GraphChecker JAR for the JUnit lifecycle only; the four completed 5–8-fault runs use the independent JUnit Platform runner.',
    }
    if (output['surefire_classpath_graphchecker_present']
            or output['surefire_classpath_skeleton_present'] or source_violations
            or any(jar_violations.values()) or any(
                entry['graphchecker_present'] or entry['skeleton_present']
                or not entry['plain_runner_present']
                for entry in actual_cp_checks.values())):
        raise RuntimeError('new-budget provenance audit failed')
    campaign.atomic_text(HERE / 'provenance-8fault.json', json.dumps(output, indent=2) + '\n')
    print('PASS: new-budget JVM, agent, and runner exclude GraphChecker/skeleton')


if __name__ == '__main__':
    main()
