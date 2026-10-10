#!/usr/bin/env python3
"""Pinned, read-only HDFS-54/55 package and node2 preflight; no Java process."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys

from class_sites import instruction_sites

BASE = Path('/users/ZhenyuLi/baseline')
HERE = BASE / 'Mallory/adapters/hdfs/cases/known-controls-node2-v1'
SOURCE = Path('/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8')
MIRROR = Path('/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2')
RELEASE = BASE / 'Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f'
AGENT = BASE / 'Mallory/adapters/hdfs/cases/heartbeat-v1/releases/d7960a24a4ce21633d870d30d796daf5cc9d9170fe9bfc2e0e9fac16986cbc58/mallory-agent-38658059.jar'
ADAPTER = AGENT.with_name('mallory-hdfs-adapter.jar')
SOURCE_DIGEST = '825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7'
RELEASE_SHA = '30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8'
AGENT_SHA = '38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9'
ADAPTER_SHA = 'd7960a24a4ce21633d870d30d796daf5cc9d9170fe9bfc2e0e9fac16986cbc58'
PINNED = {
    # Filled from immutable case-local artifacts after generation.
    'source-pins.json': '59491437f609249ab22c401eb2660f9a828abd8ed74066d7e5bd8f145551deda',
    'HDFS-54.sites.json': '8da442ab701450b8af39e19e41a62e712a9a66fb7778aaea58f07d39040718e1',
    'HDFS-55.sites.json': 'd310fd9ba4178ba02b42e120ea4f66cce33e7592522d019417ddcad789251b31',
    'HDFS-54-node2-healthy-v1.json': 'a4bb68b376aa76d909d94c2d78c9ad38291a5c199b907c9d0fd0e6f8d50a12ed',
    'HDFS-54-node2-full-v1.json': 'f7db560575d6aec61e4d1f5589d6da78f5b1814c5dc0eb6fea4c947cd2e4d4fa',
    'HDFS-55-node2-healthy-v1.json': 'eef8ae65f37bfd51bee77ef214cd1bf67ab7c4f5eb663b3f4eff48729134c848',
    'HDFS-55-node2-full-v1.json': 'cab399ffe7f385e1a30fa448fc0666e395ea6322a5cb072da931cc09a2282737',
}
MIN_FREE_BYTES = 6_000_000_000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f'missing or changed artifact: {path}')


def source_digest(root: Path, reference: dict) -> str:
    digest = hashlib.sha256()
    for relative in reference['paths']:
        path = root / relative
        if path.is_symlink():
            payload = b'L' + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b'F' + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f'source file missing: {path}')
        digest.update(os.fsencode(relative) + b'\0' + payload + b'\0')
    return digest.hexdigest()


def check_class_sites(root: Path, case: str, config: dict) -> None:
    hdfs = root / 'hadoop-hdfs-project'
    if case == 'HDFS-54':
        target = hdfs / 'hadoop-hdfs-client/target/classes/org/apache/hadoop/hdfs/FileChecksumHelper$StripedFileNonStripedChecksumComputer.class'
        descriptor, sites = instruction_sites(target, 'checksumBlocks')
        expected = {('branch', 629, 4), ('throw', 631, 1)}
        if descriptor != '()V':
            raise RuntimeError('HDFS-54 target descriptor changed')
    else:
        target = hdfs / 'hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.class'
        precursor = hdfs / 'hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/balancer/KeyManager.class'
        descriptor, sites = instruction_sites(target, 'retrieveDataEncryptionKey')
        _, upstream_sites = instruction_sites(precursor, 'newDataEncryptionKey')
        expected = {('branch', 552, 1), ('throw', 555, 1)}
        if descriptor != '(I[B)[B' or ('branch', 123, 2) not in {row[:3] for row in upstream_sites}:
            raise RuntimeError('HDFS-55 selected guard or downstream key-map guard changed')
    if not expected <= {row[:3] for row in sites}:
        raise RuntimeError(f'{case} exact branch/throw sites changed')
    require(target, config['expected_target_class_sha256'])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('HDFS-54', 'HDFS-55'), required=True)
    parser.add_argument('--mode', choices=('healthy', 'full'), required=True)
    parser.add_argument('--static', action='store_true')
    args = parser.parse_args()
    if not args.static and socket.gethostname().split('.')[0] != 'node2':
        raise RuntimeError('runtime preflight must run on node2')
    for name, expected in PINNED.items():
        require(HERE / name, expected)
    require(RELEASE / 'manifest.json', RELEASE_SHA)
    for name, expected in json.loads((RELEASE / 'manifest.json').read_text())['files'].items():
        require(RELEASE / name, expected)
    require(AGENT, AGENT_SHA)
    require(ADAPTER, ADAPTER_SHA)
    config_path = HERE / f'{args.case}-node2-{args.mode}-v1.json'
    config = json.loads(config_path.read_text())
    if (config['case_id'] != args.case or
            config['calibration_only'] != (args.mode == 'healthy') or
            config['auto_promote_if_healthy'] != (args.mode == 'full') or
            config['budget']['trials'] != 80 or config['budget']['seconds'] != 3600 or
            config['budget']['max_faults_per_trial'] != 3 or
            config['agent_jar'] != str(AGENT) or
            config['agent_properties']['adapter.jar'] != str(ADAPTER) or
            config['cwd'] != str(SOURCE) or
            config['site_file'] != str(HERE / f'{args.case}.sites.json') or
            config['allow_local_timeline_doors'] is not False or
            config['reject_coarse_roots'] is not True or
            config['require_event_time_paths'] is not True):
        raise RuntimeError('case config differs from pinned semantics')
    sites = json.loads(Path(config['site_file']).read_text())
    if not sites['doors'] or any(x['exception_class'] != 'java.io.IOException' for x in sites['doors']):
        raise RuntimeError('no real typed IOException doors')
    if args.case == 'HDFS-55':
        if not any(x['clazz'] == 'org.apache.hadoop.hdfs.server.datanode.BPOfferService'
                   and x['method'] == 'processCommandFromActive' and x['line'] == 782
                   and x['callee'].endswith('BlockPoolTokenSecretManager#addKeys(Ljava/lang/String;Lorg/apache/hadoop/hdfs/security/token/block/ExportedBlockKeys;)V')
                   for x in sites['doors']):
            raise RuntimeError('missing exact DN key-distribution IOException door')
        if not any(x['method'] == 'newDataEncryptionKey' and x['line'] == 123
                   for x in sites['targets']):
            raise RuntimeError('missing selected nonthrowing KeyManager guard')
        if not any(x['method'] == 'retrieveDataEncryptionKey' and x['line'] == 555
                   for x in sites['targets']):
            raise RuntimeError('missing distinct DN exception oracle')
    sys.path.insert(0, str(RELEASE))
    from Mallory.core.campaign import validate_config
    validation = dict(config)
    root = (SOURCE if SOURCE.is_dir() else MIRROR) if args.static else SOURCE
    if args.static:
        validation['cwd'] = str(root)
    validate_config(validation)
    for item in config['runtime_artifacts']:
        path = Path(item['path'])
        if path.is_relative_to(SOURCE):
            path = root / path.relative_to(SOURCE)
        require(path, item['sha256'])
    pins = json.loads((HERE / 'source-pins.json').read_text())
    for item in pins['paths'].values():
        require(root / item['relative'], item['sha256'])
    reference = json.loads((BASE / 'Mallory/dispatch/source_reference.json').read_text())
    reference = reference['roots']['/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3']
    if (reference['digest'] != SOURCE_DIGEST or pins['source_digest'] != SOURCE_DIGEST or
            source_digest(root, reference) != SOURCE_DIGEST):
        raise RuntimeError('Hadoop source fingerprint changed')
    check_class_sites(root, args.case, config)
    if not args.static:
        if shutil.disk_usage(BASE).free < MIN_FREE_BYTES:
            raise RuntimeError('node2 disk below 6 GB campaign and archive reserve')
        output = Path(f'/tmp/mallory-{args.case.lower().replace("-", "")}-known-v1-node2-{args.mode}')
        if output.exists():
            existing = output / 'config.json'
            if (not existing.is_file() or json.loads(existing.read_text()) != config or
                    not (output / 'checkpoint.json').is_file()):
                raise RuntimeError('existing output is not a matching resumable campaign')
        if args.mode == 'full':
            from verify_control import verify_healthy
            verify_healthy(args.case, Path(str(output).replace('-full', '-healthy')),
                           require_audit=True)
    print(json.dumps({'status': 'static_preflight_pass' if args.static else 'preflight_pass',
                      'case_id': args.case, 'mode': args.mode, 'config_sha256': PINNED[config_path.name],
                      'source_digest': SOURCE_DIGEST, 'source_root': str(root)}, sort_keys=True))


if __name__ == '__main__':
    main()
