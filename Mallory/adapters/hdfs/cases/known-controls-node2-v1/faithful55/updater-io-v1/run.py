#!/usr/bin/env python3
"""Dispatch-only encrypted MiniDFSCluster original/fixed updater-I/O differential."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import time

import prepare

HERE = Path(__file__).resolve().parent
BASE = Path('/users/ZhenyuLi/baseline')
HADOOP = Path('/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3')
JDK = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
LOCK = Path('/tmp/mallory-lanes/hdfs-identity-v8-node2.lock')
DEFAULT_OUT = Path('/tmp/mallory-hdfs55-faithful-updater-io-v1-node2')
CRASH_CASE = BASE / 'crashfuzz/cases/HDFS-55'
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar')
TEST_CLASS = 'org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer'
TEST_METHOD = 'testEncryptedBalancer0'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def static() -> dict:
    sources = prepare.generate()
    pins = json.loads((HERE / 'source-pins.json').read_text())
    if sha(prepare.CRASH / 'build_overlay.py') != pins['control_builder_sha256']:
        raise RuntimeError('historical minimal fix builder changed')
    if pins['source_commit'] != '9d50c6884666e794e45102260a4017bb31802e1b':
        raise RuntimeError('released source commit changed')
    for name in pins['local_sha256']:
        if sha(HERE / name) != pins['local_sha256'][name]:
            raise RuntimeError(f'local runner/auditor changed: {name}')
    for path, expected in pins['runtime_sha256'].items():
        if sha(Path(path)) != expected:
            raise RuntimeError(f'runtime dependency changed: {path}')
    return {'status': 'faithful55_no_jvm_preflight_pass',
            'source_pins_sha256': sha(HERE / 'source-pins.json'),
            'generated_sha256': {name: hashlib.sha256(body.encode()).hexdigest()
                                 for name, body in sorted(sources.items())},
            'jvm_executed': False, 'runtime_unverified': True}


def invoke(argv: list[str], *, cwd: Path | None = None, env: dict | None = None,
           log: Path | None = None, timeout: int | None = None) -> int:
    if log is None:
        subprocess.run(argv, cwd=cwd, env=env, timeout=timeout, check=True)
        return 0
    with log.open('w') as stream:
        try:
            return subprocess.run(argv, cwd=cwd, env=env, timeout=timeout,
                                  stdout=stream, stderr=subprocess.STDOUT,
                                  check=False).returncode
        except subprocess.TimeoutExpired:
            return 124


def classpath(env: dict) -> str:
    return subprocess.check_output([str(HADOOP / 'bin/hadoop'), 'classpath', '--glob'],
                                   env=env, text=True).strip()


def build(output: Path, hadoop_cp: str, env: dict) -> tuple[dict[str, Path], Path, Path]:
    generated = output / 'generated'
    with (output / 'source-preparation.json').open('w') as stream:
        subprocess.run([sys.executable, str(HERE / 'prepare.py'), '--emit', str(generated)],
                       check=True, stdout=stream)
    tests = HADOOP / 'share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar'
    common_tests = HADOOP / 'share/hadoop/common/hadoop-common-3.4.3-tests.jar'
    junit = HADOOP / 'share/hadoop/tools/lib/junit-4.13.2.jar'
    mockito = Path('/users/ZhenyuLi/.m2/repository/org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar')
    byte_buddy = Path('/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar')
    byte_buddy_agent = Path('/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar')
    objenesis = Path('/users/ZhenyuLi/.m2/repository/org/objenesis/objenesis/3.3/objenesis-3.3.jar')
    jars = [tests, common_tests, junit, mockito, byte_buddy, byte_buddy_agent, objenesis]
    jars += sorted((HADOOP / 'share/hadoop/tools/lib').glob('*.jar'))
    cp = os.pathsep.join([*(str(path) for path in jars), hadoop_cp])
    asm_classes = output / 'asm-classes'
    asm_classes.mkdir()
    invoke([str(JDK / 'javac'), '-proc:none', '-cp', str(ASM), '-d', str(asm_classes),
            str(generated / 'asm/PatchFaithfulSaslClient.java')], env=env)
    client_class = output / 'original-SaslDataTransferClient.class'
    import zipfile
    with zipfile.ZipFile(HADOOP / 'share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar') as archive:
        client_class.write_bytes(archive.read(
            'org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient.class'))
    common = list((generated / 'main').rglob('*.java'))
    overlays: dict[str, Path] = {}
    for mode in ('original', 'fixed'):
        overlay = output / f'{mode}-overlay'
        overlay.mkdir()
        source_files = [HERE / 'Hdfs55FaithfulProbe.java', *common,
                        *(generated / mode).rglob('*.java')]
        invoke([str(JDK / 'javac'), '-proc:none', '-cp', cp, '-d', str(overlay),
                *(str(file) for file in source_files)], env=env)
        invoke([str(JDK / 'java'), '-cp', os.pathsep.join((str(asm_classes), str(ASM))),
                'PatchFaithfulSaslClient', str(client_class), str(overlay)], env=env)
        overlays[mode] = overlay
    test_overlay = output / 'test-overlay'
    test_overlay.mkdir()
    invoke([str(JDK / 'javac'), '-proc:none', '-cp',
            os.pathsep.join((str(overlays['original']), cp)), '-d', str(test_overlay),
            *(str(file) for file in (generated / 'test').rglob('*.java'))], env=env)
    wrapper = output / 'wrapper'
    wrapper.mkdir()
    invoke([str(JDK / 'javac'), '-proc:none', '-cp', cp, '-d', str(wrapper),
            str(CRASH_CASE / 'campaign/RunOneJUnitExit.java')], env=env)
    return overlays, test_overlay, wrapper


def junit_run(output: Path, name: str, mode: str, inject: bool, overlay: Path,
              test_overlay: Path, wrapper: Path, hadoop_cp: str, env: dict) -> dict:
    trial = output / name
    trial.mkdir()
    scratch = trial / 'scratch'
    for leaf in ('data', 'tmp', 'logs'):
        (scratch / leaf).mkdir(parents=True)
    source_resources = (prepare.HDFS / 'test/resources')
    tests = HADOOP / 'share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar'
    common_tests = HADOOP / 'share/hadoop/common/hadoop-common-3.4.3-tests.jar'
    junit = HADOOP / 'share/hadoop/tools/lib/junit-4.13.2.jar'
    mockito = Path('/users/ZhenyuLi/.m2/repository/org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar')
    byte_buddy = Path('/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar')
    byte_buddy_agent = Path('/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar')
    objenesis = Path('/users/ZhenyuLi/.m2/repository/org/objenesis/objenesis/3.3/objenesis-3.3.jar')
    cp = os.pathsep.join([str(test_overlay), str(overlay), str(source_resources),
                          str(wrapper), *(str(path) for path in
                              (tests, common_tests, junit, mockito, byte_buddy,
                               byte_buddy_agent, objenesis)),
                          *(str(path) for path in sorted((HADOOP / 'share/hadoop/tools/lib').glob('*.jar'))),
                          hadoop_cp])
    argv = [str(JDK / 'java'), '-ea', '-Xmx3g',
            '-Djava.awt.headless=true', '-Djava.net.preferIPv4Stack=true',
            '-Dtest.build.data=' + str(scratch / 'data'),
            '-Djava.io.tmpdir=' + str(scratch / 'tmp'),
            '-Dhadoop.log.dir=' + str(scratch / 'logs'),
            '-Dhdfs55f.inject=' + str(inject).lower(),
            '-Dhdfs55f.waitMs=80000', '-Dhdfs55f.maxUpdaterIo=512',
            '-Dhdfs55f.maxOutageMs=120000',
            '-cp', cp, 'RunOneJUnitExit', TEST_CLASS, TEST_METHOD]
    started = time.monotonic()
    rc = invoke(argv, cwd=scratch, env=env, log=trial / 'junit.log', timeout=240)
    receipt = {'case_id': 'HDFS-55', 'variant': 'faithful_updater_io_v1',
               'name': name, 'mode': mode, 'inject_updater_io': inject,
               'returncode': rc, 'elapsed_seconds': round(time.monotonic() - started, 3),
               'test': TEST_CLASS + '#' + TEST_METHOD,
               'junit_log_sha256': sha(trial / 'junit.log'),
               'overlay': str(overlay), 'test_overlay': str(test_overlay),
               'wait_ms': 80000, 'max_updater_io': 512,
               'max_outage_ms': 120000,
               'source_pins_sha256': sha(HERE / 'source-pins.json')}
    (trial / 'manifest.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


def runtime(output: Path) -> dict:
    if os.environ.get('MALLORY_DISPATCH_ADMITTED') != '1':
        raise RuntimeError('explicit dispatch admission required')
    if socket.gethostname().split('.')[0] != 'node2':
        raise RuntimeError('faithful HDFS-55 runtime is node2 only')
    if shutil.disk_usage(BASE).free < 6_000_000_000:
        raise RuntimeError('node2 free disk below 6 GB run/archive reserve')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('w') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if output.exists():
            raise RuntimeError(f'fresh output required: {output}')
        output.mkdir(parents=True)
        env = dict(os.environ, JAVA_HOME=str(JDK.parent))
        hadoop_cp = classpath(env)
        overlays, test_overlay, wrapper = build(output, hadoop_cp, env)
        healthy = junit_run(output, 'healthy', 'original', False,
                            overlays['original'], test_overlay, wrapper, hadoop_cp, env)
        if healthy['returncode'] == 0:
            junit_run(output, 'fault-original', 'original', True,
                      overlays['original'], test_overlay, wrapper, hadoop_cp, env)
            junit_run(output, 'fault-fixed', 'fixed', True,
                      overlays['fixed'], test_overlay, wrapper, hadoop_cp, env)
            verdict = subprocess.check_output([sys.executable, str(HERE / 'audit.py'),
                                               '--output', str(output)], text=True)
        else:
            verdict = json.dumps({'case_id': 'HDFS-55', 'variant': 'faithful_updater_io_v1',
                                  'status': 'healthy_gate_failed', 'returncode': healthy['returncode'],
                                  'detection_claim': False}, indent=2, sort_keys=True) + '\n'
        (output / 'audit.json').write_text(verdict)
        archive = output / 'evidence.tar.gz'
        with tarfile.open(archive, 'w:gz') as bundle:
            for path in sorted(output.rglob('*')):
                if path.is_file() and path != archive and 'scratch' not in path.parts:
                    bundle.add(path, arcname=str(path.relative_to(output)))
        receipt = {'status': 'faithful_candidate_terminal_review',
                   'case_id': 'HDFS-55', 'source_pins_sha256': sha(HERE / 'source-pins.json'),
                   'audit_sha256': sha(output / 'audit.json'),
                   'archive_sha256': sha(archive), 'archive': str(archive),
                   'detection_claim': False}
        (output / 'terminal-receipt.json').write_text(json.dumps(receipt, indent=2,
                                                                sort_keys=True) + '\n')
        return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--static', action='store_true')
    group.add_argument('--run', action='store_true')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    preflight = static()
    print(json.dumps(preflight, sort_keys=True), flush=True)
    if args.run:
        print(json.dumps(runtime(args.output), sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
