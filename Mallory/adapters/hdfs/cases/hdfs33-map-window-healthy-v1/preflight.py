#!/usr/bin/env python3
"""Read-only HDFS-33 map-window probe preflight; never starts Java."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

BASE = Path('/users/ZhenyuLi/baseline')
HERE = Path(__file__).resolve().parent
CONFIG = HERE / 'HDFS-33-node2-healthy-v1.json'
NODE0_SOURCE = Path('/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2')
NODE2_SOURCE = Path('/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8')
SITE_SHA256 = 'afc087877deb67d0af3dc936cec06307c7ea0198747a3e740858a0c2371e04ed'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--static', action='store_true', help='check equivalent node0 source and classes')
    args = parser.parse_args()
    source = NODE0_SOURCE if args.static else NODE2_SOURCE
    config = json.loads(CONFIG.read_text())
    sys.path.insert(0, str(BASE))
    from Mallory.core.campaign import validate_config

    candidate = dict(config, cwd=str(source)) if args.static else config
    validate_config(candidate)
    assert config['case_id'] == 'HDFS-33'
    assert config['calibration_only'] is True
    assert config['auto_promote_if_healthy'] is False
    assert config['budget']['trials'] == 1
    assert config['agent_properties']['state.maps'] is True
    assert config['agent_properties']['state.fields'] is False
    assert config['healthy_gate']['door_candidate_role'].startswith('diagnostic_only_')
    assert config['site_file'] == str(HERE / 'HDFS-33.sites.json')
    assert digest(Path(config['site_file'])) == SITE_SHA256
    for row in config['runtime_artifacts']:
        path = Path(row['path'])
        if args.static and path.is_relative_to(NODE2_SOURCE):
            path = NODE0_SOURCE / path.relative_to(NODE2_SOURCE)
        if digest(path) != row['sha256']:
            raise RuntimeError(f'artifact hash mismatch: {path}')
    src = source / 'hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode'
    data_storage = (src / 'DataStorage.java').read_text()
    actor = (src / 'BPServiceActor.java').read_text()
    assert 'bpStorageMap.put(bpid, bpStorage)' in data_storage
    assert 'bpStorageMap.remove(bpId)' in data_storage
    assert 'assert bpStorage != null;' in data_storage
    assert 'resp = sendHeartBeat(requestBlockReportLease);' in actor
    assert 'catch (IOException e)' in actor
    print(json.dumps({'case_id': 'HDFS-33', 'status': 'preflight_pass',
                      'mode': 'static_node0' if args.static else 'node2',
                      'config_sha256': digest(CONFIG), 'site_sha256': SITE_SHA256,
                      'healthy_only': True, 'jvm_launched': False}, sort_keys=True))


if __name__ == '__main__':
    main()
