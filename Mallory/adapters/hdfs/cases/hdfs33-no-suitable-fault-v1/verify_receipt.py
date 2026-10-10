#!/usr/bin/env python3
"""Verify pinned HDFS-33 source-review evidence without Java."""

import hashlib
import json
import runpy
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECEIPT = HERE / 'source-receipt.json'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt['case_id'] == 'HDFS-33'
    assert receipt['status'] == 'no_suitable_existing_test_or_pinned_fault_model'
    assert receipt['full_campaign_admitted'] is False
    head = subprocess.check_output(
        ['git', '-C', receipt['source_root'], 'rev-parse', 'HEAD'], text=True).strip()
    assert head == receipt['source_commit']
    for artifact in receipt['artifacts']:
        path = Path(artifact['path'])
        if digest(path) != artifact['sha256']:
            raise RuntimeError(f'artifact hash mismatch: {path}')
    result_path = next(Path(a['path']) for a in receipt['artifacts']
                       if a['path'].endswith('HDFS-33-fresh-healthy-v2/trials/r0000/result.json'))
    result = json.loads(result_path.read_text())
    junit = result['junit_validation']
    assert (junit['tests'], junit['failures'], junit['errors']) == (1, 0, 0)
    feedback = result['feedback']
    assert feedback['target_reached'] and not feedback['target_threw']
    assert {i['node'] for i in feedback['target_instances']} == {'hdfs-cluster-1/dn0'}
    audit_path = next(Path(a['path']) for a in receipt['artifacts']
                      if a['path'].endswith('HDFS-33-fresh-healthy-v2/offline-causal-audit.json'))
    audit = json.loads(audit_path.read_text())
    assert audit['healthy_observed_path_doors'] == 0
    assert audit['report_gate_passed'] is False
    map_path = next(Path(a['path']) for a in receipt['artifacts']
                    if a['path'].endswith('HDFS-33-map-window-v1/trials/r0000/result.json'))
    map_root = map_path.parents[2]
    remote_index_path = map_root.parent / (map_root.name + '.remote-sha-index.json')
    remote_index = json.loads(remote_index_path.read_text())
    for relative, expected in remote_index['files'].items():
        if digest(map_root / relative) != expected:
            raise RuntimeError(f'remote SHA index mismatch: {relative}')
    map_audit_file = HERE.parent / 'hdfs33-map-window-healthy-v1/audit_healthy.py'
    map_audit = runpy.run_path(str(map_audit_file))['audit'](map_path.parent)
    map_result = json.loads(map_path.read_text())
    assert map_result['site_catalog_validation']['valid'] is True
    assert map_result['site_catalog_validation']['class_hash_match'] is True
    assert map_result['feedback']['target_threw'] is False
    assert map_audit['junit_1_0_0'] and map_audit['named_healthy_target_observed']
    assert map_audit['target_checks'] == 2
    assert map_audit['named_target_checks'] == 2
    assert map_audit['target_nodes'] == ['hdfs-cluster-1/dn0']
    assert map_audit['map_puts'] == 1 and map_audit['target_map_reads'] == 1
    assert [(row['put_seq'], row['read_seq']) for row in
            map_audit['same_map_key_pre_target_pairs']] == [(11, 77)]
    assert map_audit['remove_method_events'] == 0
    assert len(map_audit['diagnostic_doors_before_target']) == 4
    assert not any(door['in_closure'] for door in map_result['feedback']['doors']
                   if 'StorageLocation#makeBlockPoolDir' in door['site'] or
                      'BPServiceActor#offerService' in door['site'])
    assert map_audit['fault_campaign_admitted'] is False
    print(json.dumps({'case_id': 'HDFS-33', 'status': 'verified_source_review_hold',
                      'pinned_artifacts': len(receipt['artifacts']),
                      'map_window_evidence': 'remote_sha_index_verified',
                      'jvm_launched': False}, sort_keys=True))


if __name__ == '__main__':
    main()
