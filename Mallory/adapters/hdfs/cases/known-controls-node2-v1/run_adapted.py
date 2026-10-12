#!/usr/bin/env python3
"""Pinned, dispatch-only adapted HDFS-54 differential and HDFS-55 diagnostic."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile

BASE = Path('/users/ZhenyuLi/baseline')
HERE = BASE / 'Mallory/adapters/hdfs/cases/known-controls-node2-v1'
CRASHFUZZ = BASE / 'crashfuzz/cases'
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3')
WORK = Path('/tmp/mallory-known-controls-adapted-v1')
LOCK = Path('/tmp/mallory-lanes/hdfs-identity-v8-node2.lock')
PINS_FILE = HERE / 'adapted-pins.json'


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def preflight(case: str) -> dict:
    pins = json.loads(PINS_FILE.read_text())
    entry = pins['cases'][case]
    for row in entry['artifacts']:
        path = Path(row['path'])
        if not path.is_file() or sha(path) != row['sha256']:
            raise RuntimeError(f'adapted control artifact changed: {path}')
    if case == 'HDFS-54':
        source = (HERE / 'adapted54/StripedChecksumStaleKeyControl.java').read_text()
        if ('DFS_ENCRYPT_DATA_TRANSFER_KEY, true' not in source or
                'numDataNodes(3)' not in source or
                'XOR_2_1_POLICY_ID' not in source or
                'throw new AssertionError("HDFS-17897:' not in source):
            raise RuntimeError('HDFS-54 encrypted XOR-2-1 adaptation changed')
    else:
        manifest = json.loads((HERE / 'adapted-controls-v1.json').read_text())['controls']['HDFS-55']
        if (manifest.get('kind') != 'synthetic_missing_key_diagnostic' or
                manifest.get('detection_claim') is not False or
                manifest.get('mechanism_faithful') is not False):
            raise RuntimeError('HDFS-55 direct map override must remain diagnostic only')
        source = (HERE / 'adapted55/BlockTokenSecretManager.java').read_text()
        probe = (HERE / 'adapted55/Hdfs17899Probe.java').read_text()
        fixture = (HERE / 'adapted55/TestBalancerWithEncryptedTransfer.java').read_text()
        if (source.count('key = allKeys.get(keyId);') < 1 or
                'forceMissingAtAllKeys(keyId, blockPoolId, nonce, key != null)' not in source or
                'dn_allkeys_forced_missing=' not in probe or
                'new TestBalancer().integrationTest(conf);' not in fixture or
                '@Test(timeout=180000)' not in fixture):
            raise RuntimeError('HDFS-55 exact allKeys/one-node adaptation changed')
    return {'case_id': case, 'status': 'adapted_static_preflight_pass',
            'pins_sha256': sha(PINS_FILE), 'source_commit': pins['source_commit'],
            'runtime_unverified': True}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(script: Path, *args: str, expected: int) -> None:
    completed = subprocess.run([sys.executable, str(script), *args], check=False)
    if completed.returncode != expected:
        raise RuntimeError(f'{script.name} returned {completed.returncode}; expected {expected}')


def run_hdfs54() -> None:
    stage = HERE / 'adapted54'
    local = WORK / 'hdfs54-src'
    if local.exists():
        raise RuntimeError(f'adapted source work directory already exists: {local}')
    shutil.copytree(stage, local, ignore=shutil.ignore_patterns('__pycache__'))
    for mode, expected in (('original', 1), ('fixed', 0)):
        output = WORK / f'hdfs54-{mode}'
        if output.exists():
            raise RuntimeError(f'output exists: {output}')
        run_script(local / 'run_control.py', '--mode', mode, '--output', str(output),
                   '--timeout', '300', expected=expected)


def run_hdfs55() -> None:
    stage = HERE / 'adapted55'
    build = WORK / 'hdfs55-build'
    if build.exists():
        raise RuntimeError(f'build directory already exists: {build}')
    build.mkdir(parents=True)
    builder = load('hdfs55_overlay_builder', CRASHFUZZ / 'HDFS-55/build_overlay.py')
    builder.HERE = stage
    env = dict(os.environ, JAVA_HOME=str(builder.JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(builder.HADOOP / 'bin/hadoop'), 'classpath', '--glob'],
        env=env, text=True).strip()
    overlays = {}
    for mode in ('original', 'fixed'):
        overlay = builder.build(mode, build_dir=build, dn_server_hook=True)
        subprocess.run([str(builder.JDK / 'javac'), '-proc:none',
                        '-cp', os.pathsep.join((str(overlay), hadoop_cp)),
                        '-d', str(overlay),
                        str(stage / 'BlockTokenSecretManager.java')], check=True)
        overlays[mode] = overlay
    fixture = build / 'test-overlay'
    fixture.mkdir()
    test_cp = os.pathsep.join((str(builder.HADOOP / 'share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar'),
                               str(builder.HADOOP / 'share/hadoop/common/hadoop-common-3.4.3-tests.jar'),
                               str(builder.HADOOP / 'share/hadoop/tools/lib/junit-4.13.2.jar'),
                               hadoop_cp))
    subprocess.run([str(builder.JDK / 'javac'), '-proc:none', '-cp', test_cp,
                    '-d', str(fixture),
                    str(stage / 'TestBalancerWithEncryptedTransfer.java')], check=True)
    driver = load('hdfs55_driver', CRASHFUZZ / 'HDFS-55/run_control.py')
    driver.BUILD = build / 'driver-build'
    coverage_classes = build / 'coverage-classes'
    coverage_classes.mkdir()
    subprocess.run([str(builder.JDK / 'javac'), '-proc:none',
                    '-cp', os.pathsep.join((str(driver.JACOCO_CORE),
                                           *(str(jar) for jar in driver.ASM_JARS))),
                    '-d', str(coverage_classes),
                    str(CRASHFUZZ / 'HDFS-50/probe/src/CoverageHdfs50.java')],
                   check=True)
    driver.COVERAGE_TOOL = coverage_classes
    for name, mode, fault, expected in [('healthy', 'original', False, 0),
                                        ('fault-original', 'original', True, 1),
                                        ('fault-fixed', 'fixed', True, 0)]:
        output = WORK / f'hdfs55-{name}'
        if output.exists():
            raise RuntimeError(f'output exists: {output}')
        argv = ['--output', str(output), '--overlay', str(overlays[mode]),
                '--test-overlay', str(fixture), '--timeout', '300']
        if fault:
            argv += ['--inject', '--dn-reject-persistent']
        previous = sys.argv
        try:
            sys.argv = [str(CRASHFUZZ / 'HDFS-55/run_control.py'), *argv]
            try:
                driver.main()
                rc = 0
            except SystemExit as exit_status:
                rc = int(exit_status.code or 0)
        finally:
            sys.argv = previous
        if rc != expected:
            raise RuntimeError(f'HDFS-55 {name} returned {rc}; expected {expected}')


def finalize(case: str) -> dict:
    audit = subprocess.run([sys.executable, str(HERE / 'audit_adapted.py'),
                            '--case', case], check=True, capture_output=True, text=True)
    verdict = json.loads(audit.stdout)
    names = (['hdfs54-original', 'hdfs54-fixed'] if case == 'HDFS-54' else
             ['hdfs55-healthy', 'hdfs55-fault-original', 'hdfs55-fault-fixed'])
    archive = WORK / f'{case.lower()}-adapted-evidence.tar.gz'
    if archive.exists():
        raise RuntimeError(f'adapted evidence archive already exists: {archive}')
    with tarfile.open(archive, 'w:gz') as bundle:
        for name in names:
            directory = WORK / name
            for leaf in ('manifest.json', 'junit.log', 'runtime_trace.jsonl', 'jacoco.exec',
                         'covered_probes.txt', 'covered_methods.txt',
                         'covered_branch_counts.txt', 'covered_lines.txt'):
                path = directory / leaf
                if path.is_file():
                    bundle.add(path, arcname=f'{name}/{leaf}')
        build = WORK / ('hdfs54-src/build' if case == 'HDFS-54' else 'hdfs55-build')
        for path in build.rglob('*.class'):
            bundle.add(path, arcname=str(path.relative_to(WORK)))
    receipt = {'case_id': case, 'status': 'adapted_terminal_audited',
               'source_pins_sha256': sha(PINS_FILE), 'verdict': verdict,
               'evidence_archive': str(archive), 'evidence_archive_sha256': sha(archive),
               'new_bug': False}
    destination = WORK / f'{case.lower()}-adapted-terminal-receipt.json'
    temporary = destination.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    temporary.replace(destination)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('HDFS-54', 'HDFS-55'), required=True)
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.static == args.run:
        parser.error('choose exactly one of --static or --run')
    receipt = preflight(args.case)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    if args.static:
        return
    if os.environ.get('MALLORY_DISPATCH_ADMITTED') != '1':
        raise RuntimeError('adapted control requires explicit dispatch admission')
    if socket.gethostname().split('.')[0] != 'node2':
        raise RuntimeError('adapted control must run on node2')
    if shutil.disk_usage(BASE).free < 6_000_000_000:
        raise RuntimeError('node2 disk below 6 GB run and archive reserve')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('w') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        WORK.mkdir(exist_ok=True)
        (run_hdfs54 if args.case == 'HDFS-54' else run_hdfs55)()
        receipt = finalize(args.case)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
