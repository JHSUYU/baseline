#!/usr/bin/env python3
"""Offline SHA and semantic gate for the HBASE-34 recheck. Starts no JVM."""

import argparse
import hashlib
import json
import socket
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6')
DIST = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib')
TARGET = 'org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager#retrievePassword(Lorg/apache/hadoop/hbase/security/token/AuthenticationTokenIdentifier;)[B@159:branch:7'
RELEASE = REPO / 'Mallory/dispatch/releases/dc5ee9f0a9cb8dec77813d84389b36759068eabecee4bf74bc45c25afe2b0857'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise SystemExit(message)


def pinned(path, digest):
    require(path.is_file() and sha(path) == digest, f'missing or changed: {path}')


def main(mode, node1):
    receipt = json.loads((HERE / 'stage-receipt.json').read_text())
    for name, digest in receipt['files'].items():
        pinned(HERE / name, digest)
    healthy = json.loads((HERE / 'healthy.json').read_text())
    full = json.loads((HERE / 'full.json').read_text())
    sites = json.loads((HERE / 'sites.json').read_text())
    for cfg in (healthy, full):
        require(cfg['case_id'] == 'HBASE-34' and cfg['target']['check_sites'] == [TARGET],
                'selected guard changed')
        require(cfg['target']['throw_site'].endswith('@160:throw:1'), 'throw changed')
        require(cfg['cluster_test'].endswith('TestTokenAuthentication#testTokenCreation'),
                'existing JUnit changed')
        require(cfg['agent_properties']['auto.io.doors'] is False and
                cfg['allow_local_timeline_doors'] is True, 'typed door policy changed')
        require(cfg['site_file'] == str(HERE / 'sites.json'), 'site path changed')
        require(cfg['core_release']['release_id'] == RELEASE.name, 'core release changed')
    require(healthy['budget'] == {'trials': 1, 'seconds': 900,
                                  'trial_timeout_seconds': 600,
                                  'max_faults_per_trial': 1} and
            full['budget'] == {'trials': 80, 'seconds': 3600,
                               'trial_timeout_seconds': 600,
                               'max_faults_per_trial': 3}, 'budget changed')
    require(healthy['calibration_only'] is True and
            full['calibration_only'] is False and
            full['auto_promote_if_healthy'] is True, 'campaign phase changed')
    require(len(sites['doors']) == 1 and sites['doors'][0]['method'] == 'exists' and
            sites['doors'][0]['line'] == 250 and
            sites['doors'][0]['exception_class'] ==
            'org.apache.zookeeper.KeeperException$ConnectionLossException',
            'typed ZooKeeper door changed')
    require(sites['nodeBindings'] == [{
        'class': 'org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager',
        'method': 'retrievePassword',
        'descriptor': '(Lorg/apache/hadoop/hbase/security/token/AuthenticationTokenIdentifier;)[B',
        'field': 'idSeq', 'prefix': 'token-keyseq-'}], 'case-local actor binding changed')
    pins = {
        'hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java':
            '457a036cbbaaa6a1b0d66d2f4e35913933e431ef70409bbcaff7f2e59c43d51f',
        'hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/ZKSecretWatcher.java':
            receipt['source_sha256']['ZKSecretWatcher.java'],
        'hbase-server/src/test/java/org/apache/hadoop/hbase/security/token/TestTokenAuthentication.java':
            'acc0dc7fc7a9a8ca9b20314e594ca9840e4afdd0676cdedaa321704b66cc5f2e',
        'hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/RecoverableZooKeeper.java':
            'f946cd3195c5969b55ce5d079c272a7b12d673c5406a98ef026dc8fcea18fa88',
        'hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/ZKUtil.java':
            '413a0487863e7b7c8c5299f939eaec45ac33321fec8af2c5d160b64c7cf04b40',
    }
    for name, digest in pins.items():
        pinned(SOURCE / name, digest)
    pinned(DIST / 'hbase-server-2.6.6.jar',
           '27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696')
    pinned(DIST / 'hbase-zookeeper-2.6.6.jar',
           '6ad67305af4910e61e324034cab9ce0f50b966ce203c195581daeff552a8b957')
    with zipfile.ZipFile(DIST / 'hbase-server-2.6.6.jar') as jar:
        target = jar.read('org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.class')
    require(hashlib.sha256(target).hexdigest() ==
            '29ff2466145be015e2c1cb5af8ce145367b40dc5ef5209d84fb86c79381172f0',
            'compiled target changed')
    pinned(RELEASE / 'manifest.json',
           '929bddbe489b5cfb34fcb21047ea736831788e946b6401de669575d10174ca9f')
    if node1:
        require(socket.gethostname().split('.')[0] == 'node1', 'wrong host')
        cfg = healthy if mode == 'healthy' else full
        require(Path(cfg['cwd']).is_dir(), 'source-equivalent tree missing')
        for artifact in cfg['runtime_artifacts']:
            pinned(Path(artifact['path']), artifact['sha256'])
        output = REPO / 'data/mallory/cases/HBASE-34/campaigns' / ('broad-healthy-v1' if mode == 'healthy' else 'broad-full-v1')
        require(not output.exists() and not Path(str(output) + '.worker.log').exists(),
                f'output already exists: {output}')
    print(f'PASS HBASE-34 {mode} offline preflight; JVM runs=0')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('healthy', 'full'), required=True)
    parser.add_argument('--node1', action='store_true')
    args = parser.parse_args()
    main(args.mode, args.node1)
