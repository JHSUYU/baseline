#!/usr/bin/env python3
"""Source-only exact-byte and healthy-only gate. Does not launch a cluster JVM."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6')
JAR = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-client-2.6.6.jar')
EXPECTED = {
    'hbase-client/src/main/java/org/apache/hadoop/hbase/MetaTableAccessor.java':
        '1231841a2cdae7a9e2b2dd7354da624dc153fa6862b65e7aa0a22515f80881cd',
    'hbase-client/src/main/java/org/apache/hadoop/hbase/client/ResultBoundedCompletionService.java':
        'fff82effe9cc1ac8c89eef774de41af5e042f51d35687ce2646c2a21884dcf01',
    'hbase-client/src/main/java/org/apache/hadoop/hbase/client/ClientScanner.java':
        '14ba212ac62d94ce74f05644aa0ae7a50ce4844ef73665093d46cc1b82273803',
}
CLASSES = {
    'org/apache/hadoop/hbase/MetaTableAccessor.class':
        'f8e84aaa560a1cdfd3e181beb001cb6d56e2aafd2504579b8c39ce9bc5d2543b',
    'org/apache/hadoop/hbase/client/ResultBoundedCompletionService$QueueingFuture.class':
        'df7b42a5ed86f4677a141eb5c0d127d42752e45a8eb00e9a1665c8c65b703bee',
}
OVERLAY_SHA = '2b13d86a087591544ad1a8133e4571e167e4b93aa7cb49919e33f349b9b85127'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check():
    for name, sha in EXPECTED.items():
        assert digest((SOURCE / name).read_bytes()) == sha, name
    assert digest(JAR.read_bytes()) == 'b3c9537a0c5f4b057134c59298b453ae207d2e6279be66d71c80da36d0d2de54'
    with ZipFile(JAR) as archive:
        for name, sha in CLASSES.items():
            assert digest(archive.read(name)) == sha, name
    assert digest((ROOT / 'releases/2b13d86a08759154/adapter.jar').read_bytes()) == OVERLAY_SHA
    config = json.loads((ROOT / 'HBASE-35-hbck-scanner-consume-v3-healthy.json').read_text())
    assert config['case_id'] == 'HBASE-35'
    assert config['calibration_only'] is True
    assert config['require_event_time_paths'] is True
    assert config['reject_coarse_roots'] is True
    assert config['allow_local_timeline_doors'] is False
    assert config['mapping']['overlay_adapter_sha256'] == OVERLAY_SHA
    assert config['mapping']['healthy_seed_verified'] is False
    assert config['core_release']['release_id'] == 'fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f'
    print('HBASE-35 v3 source, compiled bytecode, adapter, and healthy-only config verified')


if __name__ == '__main__':
    check()
