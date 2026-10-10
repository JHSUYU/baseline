#!/usr/bin/env python3
"""Immutable offline gate for HBASE-34 healthy-only admission."""

import argparse
import gzip
import hashlib
import json
import socket
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6')
DIST = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib')
ARCHIVE = REPO / 'data/mallory/evidence_archives/calibration/HBASE-33.tar.gz'
RELEASE = REPO / 'Mallory/dispatch/releases/dc5ee9f0a9cb8dec77813d84389b36759068eabecee4bf74bc45c25afe2b0857'
OUTPUT = REPO / 'data/mallory/cases/HBASE-34/campaigns/named-exists-healthy-v2'
TARGET = ('org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager'
          '#retrievePassword(Lorg/apache/hadoop/hbase/security/token/'
          'AuthenticationTokenIdentifier;)[B@159:branch:7')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise SystemExit(message)


def pinned(path, digest):
    require(path.is_file() and sha(path) == digest, f'missing or changed: {path}')


def main(node1):
    receipt = json.loads((HERE / 'stage-receipt.json').read_text())
    for name, digest in receipt['files'].items():
        pinned(HERE / name, digest)
    config = json.loads((HERE / 'healthy.json').read_text())
    sites = json.loads((HERE / 'sites.json').read_text())
    require(config['case_id'] == 'HBASE-34' and
            config['cluster_test'] ==
            'org.apache.hadoop.hbase.security.token.TestTokenAuthentication#testTokenCreation' and
            config['target']['check_sites'] == [TARGET] and
            config['target']['throw_site'].endswith('@160:throw:1'),
            'selected case, JUnit, or guard changed')
    require(config['calibration_only'] is True and
            config['auto_promote_if_healthy'] is False and
            config['budget'] == {'trials': 1, 'seconds': 900,
                                 'trial_timeout_seconds': 600,
                                 'max_faults_per_trial': 1},
            'healthy-only budget changed')
    require(config['site_file'] == str(HERE / 'sites.json') and
            config['agent_properties']['auto.io.doors'] is False and
            config['agent_include'] == [
                'org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager',
                'org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper'],
            'case-local typed instrumentation changed')
    require(sites['doors'] == [{
        'clazz': 'org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper',
        'method': 'exists',
        'descriptor': '(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/zookeeper/data/Stat;',
        'line': 250,
        'callee': 'org.apache.zookeeper.ZooKeeper#exists(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/zookeeper/data/Stat;',
        'exception_class': 'org.apache.zookeeper.KeeperException$ConnectionLossException'}],
        'typed exists door changed')
    require(sites['nodeBindings'] == [
        {'class': 'org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager',
         'method': 'retrievePassword',
         'descriptor': '(Lorg/apache/hadoop/hbase/security/token/AuthenticationTokenIdentifier;)[B',
         'field': 'idSeq', 'prefix': 'token-keyseq-'},
        {'class': 'org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper',
         'method': 'exists',
         'descriptor': '(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/zookeeper/data/Stat;',
         'getter': 'getSessionId', 'prefix': 'zk-session-'}],
        'actor bindings changed')
    pinned(ARCHIVE, receipt['archived_passing_calibration_sha256'])
    with tarfile.open(ARCHIVE, 'r:gz') as archive:
        trace = gzip.decompress(archive.extractfile('trials/r0000/events.jsonl.gz').read())
        stderr = archive.extractfile('trials/r0000/stderr.log').read().decode('utf-8', 'replace')
    events = [json.loads(line) for line in trace.splitlines()]
    selected = [e for e in events if e.get('site') == TARGET and
                e.get('type') == 'BRANCH' and e.get('outcome') == 'TAKEN']
    require([e['seq'] for e in selected] == [43, 90] and
            'MALLORY_JUNIT found=2 succeeded=2 failed=0' in stderr,
            'archived passing exact-target evidence changed')
    for relative, digest in receipt['source_sha256'].items():
        pinned(SOURCE / relative, digest)
    pinned(DIST / 'hbase-server-2.6.6.jar',
           '27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696')
    pinned(DIST / 'hbase-zookeeper-2.6.6.jar',
           '6ad67305af4910e61e324034cab9ce0f50b966ce203c195581daeff552a8b957')
    with zipfile.ZipFile(DIST / 'hbase-server-2.6.6.jar') as jar:
        target = jar.read('org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.class')
    require(hashlib.sha256(target).hexdigest() ==
            '29ff2466145be015e2c1cb5af8ce145367b40dc5ef5209d84fb86c79381172f0',
            'compiled target changed')
    with zipfile.ZipFile(DIST / 'hbase-zookeeper-2.6.6.jar') as jar:
        door_class = jar.read('org/apache/hadoop/hbase/zookeeper/RecoverableZooKeeper.class')
    require(hashlib.sha256(door_class).hexdigest() == receipt['door_class_sha256'],
            'compiled door class changed')
    pinned(RELEASE / 'manifest.json',
           '929bddbe489b5cfb34fcb21047ea736831788e946b6401de669575d10174ca9f')
    if node1:
        require(socket.gethostname().split('.')[0] == 'node1', 'wrong host')
        require(Path(config['cwd']).is_dir(), 'source-equivalent tree missing')
        for artifact in config['runtime_artifacts']:
            pinned(Path(artifact['path']), artifact['sha256'])
        require(not OUTPUT.exists() and not Path(str(OUTPUT) + '.worker.log').exists(),
                'healthy output already exists')
    print('PASS HBASE-34 named-exists healthy-v2 offline preflight; JVM runs=0')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--node1', action='store_true')
    main(parser.parse_args().node1)
