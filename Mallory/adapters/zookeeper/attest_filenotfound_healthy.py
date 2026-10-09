#!/usr/bin/env python3
"""Attest the exact ZK12 FileNotFoundException door in a healthy cluster run."""

import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path('/users/ZhenyuLi/baseline')
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7')
PATCHED = Path('/users/ZhenyuLi/.mallory-worktrees/zookeeper')
OUT = ROOT / 'data/mallory/calibration_fa5f_node0/ZOOKEEPER-12-filenotfound-v1'
ADMISSION = ROOT / 'data/mallory/admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-healthy.json'
TARGET = 'org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1193:branch:3'
DOOR = 'org.apache.zookeeper.server.quorum.QuorumPeer#readLongFromFile(Ljava/lang/String;)J@2190:door:1'
CLASS = PATCHED / 'zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/QuorumPeer.class'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    result = json.loads((OUT / 'result.json').read_text())
    audit = json.loads((OUT / 'offline-causal-audit.json').read_text())
    trial = json.loads((OUT / 'trials/r0000/result.json').read_text())
    raw = gzip.decompress((OUT / 'trials/r0000/events.jsonl.gz').read_bytes())
    events = [json.loads(line) for line in raw.splitlines()]
    by_seq = {event['seq']: event for event in events}
    catalog = [json.loads(line) for line in
               (OUT / 'trials/r0000/sites.jsonl').read_text().splitlines()]
    door_catalog = [row for row in catalog if row.get('type') == 'DOOR_OBSERVED'
                    and row.get('site') == DOOR]
    assert len(door_catalog) == 1
    assert door_catalog[0]['exception_class'] == 'java.io.FileNotFoundException'
    assert door_catalog[0]['callee'] == 'java.io.BufferedReader#readLine()Ljava/lang/String;'
    assert door_catalog[0]['bytecode_sha256'] == sha(CLASS)
    assert result['status'] == 'calibration_complete' and result['healthy_seed_valid']
    assert result['healthy_junit_validation']['status'] == 'passed'
    assert result['healthy_junit_validation']['tests'] == 1
    assert result['runtime_attestation']['valid']
    assert result['runtime_attestation']['bound_nodes'] == ['zk0']
    assert result['runtime_attestation']['observed_target_class_sha256'] == sha(CLASS)
    assert audit['campaign_result_sha256'] == sha(OUT / 'result.json')
    assert audit['report_gate_passed'] and audit['healthy_closure_proven']
    assert audit['healthy_closure_evidence_types'] == ['observed_local_timeline']
    assert audit['healthy_local_timeline_doors'] == 5
    assert audit['healthy_observed_path_doors'] == 0
    assert trial['events_evidence']['raw_sha256'] == hashlib.sha256(raw).hexdigest()
    assert trial['events_evidence']['gzip_sha256'] == sha(OUT / 'trials/r0000/events.jsonl.gz')
    checks = [event for event in events if event['type'] == 'TARGET_CHECK'
              and event['site'] == TARGET and event['node'] == 'zk0']
    throws = [event for event in events if event['type'] == 'TARGET_THROW']
    assert len(checks) == 3 and not throws
    for seq, ordinal in ((652, 1), (653, 2), (654, 3)):
        door = by_seq[seq]
        assert door['type'] == 'DOOR_OBSERVED' and door['site'] == DOOR
        assert door['node'] == 'zk0' and door['epoch'] == 2
        assert door['door_ordinal'] == ordinal
        assert door['exception_class'] == 'java.io.FileNotFoundException'
    target = by_seq[655]
    assert target['type'] == 'TARGET_CHECK' and target['site'] == TARGET
    assert all(by_seq[seq]['thread_id'] == target['thread_id'] and
               by_seq[seq]['occurrence'] == target['occurrence']
               for seq in (652, 653, 654))
    assert any(row['door_event_id'] == by_seq[654]['id'] and
               row['target_check_event_id'] == target['id'] and
               row['kind'] == 'observed_local_timeline'
               for row in audit['healthy_local_timeline_evidence_sample'])

    config = ROOT / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-12-fa5f-filenotfound-healthy.json'
    site = ROOT / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-12-fa5f-filenotfound-healthy.sites.json'
    review = ROOT / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-12-fa5f-filenotfound-source-review.json'
    qsource = SOURCE / 'zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java'
    tsource = SOURCE / 'zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest.java'
    receipt = {
        'schema_version': 1,
        'case_id': 'ZOOKEEPER-12',
        'status': 'healthy_precise_filenotfound_door_observed',
        'selector': result['cluster_test'],
        'attempt_id': result['last_dispatch_attempt_id'],
        'duration_seconds': result['duration_seconds'],
        'junit': result['healthy_junit_validation'],
        'target': {'check_site': TARGET, 'node': 'zk0',
                   'check_count': len(checks), 'throw_count': len(throws),
                   'last_check_event_id': target['id']},
        'door': {'site': DOOR, 'exception_class': 'java.io.FileNotFoundException',
                 'callee': door_catalog[0]['callee'],
                 'candidate_accepted_epoch_point': {'node': 'zk0', 'epoch': 2,
                                                    'door_ordinal': 3},
                 'candidate_event_id': by_seq[654]['id'],
                 'preceding_same_occurrence_event_ids':
                     [by_seq[seq]['id'] for seq in (652, 653)],
                 'target_check_event_id': target['id'],
                 'evidence_kind': 'observed_local_timeline',
                 'observed_graph_path_doors': 0,
                 'ordinal_rationale': 'For zk0 epoch2, source control flow reads currentEpoch, currentEpoch.tmp, then acceptedEpoch before the selected guard; the three consecutive @2190 door ordinals are 1,2,3. The trace does not record the filename argument.'},
        'artifact_sha256': {
            'config': sha(config), 'site_file': sha(site), 'source_review': sha(review),
            'overlay_receipt': sha(ROOT / 'Mallory/adapters/zookeeper/zookeeper-3.8.7-overlay.json'),
            'core_manifest': sha(ROOT / 'Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f/manifest.json'),
            'agent_jar': sha(ROOT / 'Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar'),
            'compiled_class': sha(CLASS), 'result': sha(OUT / 'result.json'),
            'offline_audit': sha(OUT / 'offline-causal-audit.json'),
            'trial_result': sha(OUT / 'trials/r0000/result.json'),
            'trial_events_gzip': sha(OUT / 'trials/r0000/events.jsonl.gz'),
            'trial_events_raw': hashlib.sha256(raw).hexdigest(),
            'site_catalog': sha(OUT / 'trials/r0000/sites.jsonl'),
        },
        'pristine_source_sha256': {'QuorumPeer.java': sha(qsource),
                                   'CurrentEpochWriteFailureTest.java': sha(tsource)},
        'fault_campaign_admission': False,
    }
    ADMISSION.parent.mkdir(parents=True, exist_ok=True)
    ADMISSION.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'receipt': str(ADMISSION), 'sha256': sha(ADMISSION)}))


if __name__ == '__main__':
    main()
