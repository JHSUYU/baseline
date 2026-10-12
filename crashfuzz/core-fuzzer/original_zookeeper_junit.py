#!/usr/bin/env python3
"""Run an unchanged ZooKeeper 3.8.7 embedded-cluster JUnit Jupiter method."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
SOURCE = Path('/users/ZhenyuLi/zk10-independent/source')
REPORT = (SOURCE / 'zookeeper-server/target/surefire-reports/'
          'TEST-org.apache.zookeeper.test.QuorumRestartTest.xml')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--test-class', required=True)
    parser.add_argument('--test-method', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--static-selection', type=Path, required=True)
    parser.add_argument('--fault-trial', type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--worker-id', type=int)
    parser.add_argument('--worker-count', type=int, default=8)
    args = parser.parse_args()
    worker_id = (args.worker_id if args.worker_id is not None else
                 int(args.case_id.rsplit('-', 1)[1]) % args.worker_count)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / 'scratch'
    shutil.rmtree(scratch, ignore_errors=True)
    (scratch / 'temp').mkdir(parents=True)
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    test_cp = next(row.get('value') for row in props
                   if row.get('name') == 'java.class.path')
    first = test_cp.split(os.pathsep, 1)[0]
    marker = '/zookeeper-server/target/test-classes'
    if marker not in first:
        raise ValueError('Surefire classpath lacks ZooKeeper test classes')
    test_cp = test_cp.replace(first.split(marker, 1)[0], str(SOURCE))
    agent = HERE.parent / 'runtime-agent/target/crashfuzz-runtime-agent-0.1.0.jar'
    if not agent.is_file():
        raise FileNotFoundError(agent)
    build = HERE / 'build-original-zookeeper-junit'
    build.mkdir(parents=True, exist_ok=True)
    cp = os.pathsep.join([str(build), test_cp])
    runner = HERE / 'RunOriginalJupiter.java'
    target = build / 'RunOriginalJupiter.class'
    if not target.is_file() or target.stat().st_mtime_ns < runner.stat().st_mtime_ns:
        subprocess.run([str(JAVA / 'javac'), '-cp', cp, '-d', str(build),
                        str(runner)], check=True)
    command = [str(JAVA / 'java'), '-ea', '-Xmx1g', '-Djava.awt.headless=true',
               '-Dsun.reflect.noInflation=true',
               '-Djava.io.tmpdir=' + str(scratch / 'temp'),
               '-Dbuild.test.dir=' + str(scratch / 'test-data'),
               '-Dtest.junit.threads=' + str(args.worker_count),
               '-Dzookeeper.junit.threadid=' + str(worker_id),
               '-javaagent:' + str(agent), '-cp', cp, 'RunOriginalJupiter',
               args.test_class, args.test_method]
    env = dict(os.environ, JAVA_HOME=str(JAVA.parent),
               CRASHFUZZ_STATIC_SELECTION=str(args.static_selection.resolve(strict=True)),
               CAUSYNTH_TRACE_OUTPUT_DIR=str(output))
    if args.fault_trial:
        env['CAUSYNTH_FAULT_TRIAL'] = str(args.fault_trial.resolve(strict=True))
    started = time.monotonic()
    with (output / 'junit.log').open('w') as log:
        try:
            code = subprocess.run(command, cwd=SOURCE / 'zookeeper-server',
                                  env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    result = {'case_id': args.case_id,
              'cluster_test': args.test_class + '#' + args.test_method,
              'returncode': code, 'elapsed_seconds': round(time.monotonic() - started, 3),
              'trace': str(output / 'runtime_trace.jsonl'),
              'junit_log': str(output / 'junit.log')}
    (output / 'manifest.json.tmp').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'manifest.json.tmp').replace(output / 'manifest.json')
    shutil.rmtree(scratch, ignore_errors=True)
    print(json.dumps(result), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
