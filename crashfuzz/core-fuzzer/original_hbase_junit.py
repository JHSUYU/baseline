#!/usr/bin/env python3
"""Run an unchanged HBase 2.6.6 embedded-cluster JUnit Jupiter method."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build-original-hbase-junit'
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
HBASE = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6')
HADOOP = Path('/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0')
LAUNCHER = next((HERE.parent / 'vendor').glob('*junit-platform-launcher-1.13.4.jar'),
                HERE.parent / 'vendor/junit-platform-launcher-1.13.4.jar')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--test-class', required=True)
    parser.add_argument('--test-method', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--static-selection', type=Path, required=True)
    parser.add_argument('--fault-trial', type=Path)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / 'scratch'
    shutil.rmtree(scratch, ignore_errors=True)
    (scratch / 'tmp').mkdir(parents=True)
    if not LAUNCHER.is_file():
        raise FileNotFoundError(LAUNCHER)
    agent = HERE.parent / 'runtime-agent/target/crashfuzz-runtime-agent-0.1.0.jar'
    if not agent.is_file():
        raise FileNotFoundError(agent)
    # The binary distribution contains both 1.0.0-M20 and 2.1.7 Apache
    # Directory API jars. MiniKdc in HBase's security tests uses the M20
    # classes; wildcard ordering can otherwise mix Oid 2.1.7 with I18n M20.
    directory_api = [HBASE / 'lib/api-asn1-api-1.0.0-M20.jar',
                     HBASE / 'lib/api-i18n-1.0.0-M20.jar']
    mini_kdc_crypto = [Path.home() / '.m2/repository/org/bouncycastle' /
                       f'{module}-jdk15on/1.60/{module}-jdk15on-1.60.jar'
                       for module in ('bcprov', 'bcpkix')]
    if any(not jar.is_file() for jar in directory_api + mini_kdc_crypto):
        raise FileNotFoundError('HBase MiniKdc test dependencies are missing')
    ssl_classes = scratch / 'test-classes'
    cp = os.pathsep.join([str(ssl_classes), str(BUILD), str(LAUNCHER),
                          str(HBASE / 'conf'),
                          *(str(jar) for jar in directory_api + mini_kdc_crypto),
                          str(HBASE / 'lib/*'),
                          str(HBASE / 'lib/client-facing-thirdparty/*'),
                          str(HADOOP / 'share/hadoop/common/hadoop-common-2.10.0-tests.jar'),
                          str(HADOOP / 'share/hadoop/common/lib/*')])
    if args.test_class.endswith('.TestGenerateDelegationToken'):
        utility = (HERE / 'hbase-support/src/org/apache/hadoop/hbase/http/ssl/'
                   'KeyStoreTestUtil.java')
        ssl_classes.mkdir(parents=True)
        subprocess.run([str(JAVA / 'javac'), '-cp', cp, '-d', str(ssl_classes),
                        str(utility)], check=True)
    source = HERE / 'RunOriginalJupiter.java'
    target = BUILD / 'RunOriginalJupiter.class'
    with (HERE / '.build-original-hbase-junit.lock').open('a+') as build_lock:
        fcntl.flock(build_lock, fcntl.LOCK_EX)
        if not target.is_file() or target.stat().st_mtime_ns < source.stat().st_mtime_ns:
            BUILD.mkdir(parents=True, exist_ok=True)
            subprocess.run([str(JAVA / 'javac'), '-cp', cp, '-d', str(BUILD),
                            str(source)], check=True)
    command = [str(JAVA / 'java'), '-ea', '-Xmx4g',
               '-Djava.io.tmpdir=' + str(scratch / 'tmp'),
               '-Dtest.build.data.basedirectory=' + str(scratch),
               '-javaagent:' + str(agent), '-cp', cp, 'RunOriginalJupiter',
               args.test_class, args.test_method]
    env = dict(os.environ, HBASE_HOME=str(HBASE), JAVA_HOME=str(JAVA.parent),
               CRASHFUZZ_STATIC_SELECTION=str(args.static_selection.resolve(strict=True)),
               CAUSYNTH_TRACE_OUTPUT_DIR=str(output))
    if args.fault_trial:
        env['CAUSYNTH_FAULT_TRIAL'] = str(args.fault_trial.resolve(strict=True))
    started = time.monotonic()
    with (output / 'junit.log').open('w') as log:
        try:
            code = subprocess.run(command, cwd=scratch, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=args.timeout).returncode
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
