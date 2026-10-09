#!/usr/bin/env python3
"""Seal the existing ZK10 observer healthy trace and bounded fault-model review."""

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path('/users/ZhenyuLi/baseline')
OUT = ROOT / 'data/mallory/calibration_fa5f_node0/ZOOKEEPER-10-observer-v1'
ADMISSION = ROOT / 'data/mallory/admissions'
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7')
PATCHED = Path('/users/ZhenyuLi/.mallory-worktrees/zookeeper')
CLASS = 'zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/ObserverMaster.class'
QUORUM = 'zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/'
PREFIX = 'org.apache.zookeeper.server.quorum.ObserverMaster#removeProposedPacket(J)Lorg/apache/zookeeper/server/quorum/QuorumPacket;'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, document):
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')
    return sha(path)


def main():
    result = json.loads((OUT / 'result.json').read_text())
    audit = json.loads((OUT / 'offline-causal-audit.json').read_text())
    trial = json.loads((OUT / 'trials/r0000/result.json').read_text())
    events_gz = OUT / 'trials/r0000/events.jsonl.gz'
    raw = gzip.decompress(events_gz.read_bytes())
    events = [json.loads(line) for line in raw.splitlines()]
    by_seq = {event['seq']: event for event in events}
    config = ROOT / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-healthy.json'
    sites = ROOT / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-healthy.sites.json'
    review = ROOT / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-source-review.json'

    assert result['status'] == 'calibration_complete' and result['healthy_seed_valid']
    assert result['healthy_junit_validation']['status'] == 'passed'
    assert result['healthy_junit_validation']['tests'] == 2
    assert result['runtime_attestation']['valid']
    assert result['runtime_attestation']['bound_nodes'] == ['zk1']
    assert result['runtime_attestation']['observed_target_class_sha256'] == sha(PATCHED / CLASS)
    assert audit['report_gate_passed'] and audit['healthy_closure_proven']
    assert audit['healthy_closure_evidence_types'] == ['observed_graph_path']
    assert audit['healthy_observed_path_doors'] == 13
    assert audit['campaign_result_sha256'] == sha(OUT / 'result.json')
    assert trial['events_evidence']['gzip_sha256'] == sha(events_gz)
    assert trial['events_evidence']['raw_sha256'] == hashlib.sha256(raw).hexdigest()
    checks = [event for event in events if event['type'] == 'TARGET_CHECK' and event['site'] == PREFIX + '@368:branch:3']
    throws = [event for event in events if event['type'] == 'TARGET_THROW' and event['site'] == PREFIX + '@374:throw:1']
    assert len(checks) == 7 and not throws and all(event['node'] == 'zk1' for event in checks)
    in_closure = [door for door in trial['feedback']['doors'] if door['in_closure']]
    counts = Counter((door['site'], door['point']['node'], door['point']['epoch']) for door in in_closure)
    assert counts == {
        ('zookeeper.quorum.archive.writeRecord', 'zk2', 0): 10,
        ('zookeeper.quorum.archive.readRecord', 'zk1', 0): 3,
    }
    chain = [93, 94, 95, 96, 97, 98, 99]
    assert [by_seq[seq]['type'] for seq in chain] == [
        'DOOR_OBSERVED', 'SEND', 'RECV', 'REGION_ENTER', 'REGION_ENTER', 'REGION_ENTER', 'TARGET_CHECK'
    ]
    assert by_seq[94]['correlation'] == by_seq[95]['correlation']
    assert by_seq[99]['node'] == 'zk1' and by_seq[99]['epoch'] == 0
    assert by_seq[95]['thread_id'] == by_seq[96]['thread_id'] == by_seq[99]['thread_id']

    artifact_hashes = {
        'config': sha(config),
        'site_file': sha(sites),
        'source_review': sha(review),
        'overlay_receipt': sha(ROOT / 'Mallory/adapters/zookeeper/zookeeper-3.8.7-overlay.json'),
        'core_manifest': sha(ROOT / 'Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f/manifest.json'),
        'agent_jar': sha(ROOT / 'Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar'),
        'compiled_target_class': sha(PATCHED / CLASS),
        'result': sha(OUT / 'result.json'),
        'offline_audit': sha(OUT / 'offline-causal-audit.json'),
        'trial_result': sha(OUT / 'trials/r0000/result.json'),
        'trial_events_gzip': sha(events_gz),
        'trial_events_raw': hashlib.sha256(raw).hexdigest(),
        'site_catalog': sha(OUT / 'trials/r0000/sites.jsonl'),
    }
    source_hashes = {name: sha(SOURCE / QUORUM / name) for name in (
        'ObserverMaster.java', 'Follower.java', 'LearnerHandler.java', 'FollowerZooKeeperServer.java')}
    ADMISSION.mkdir(parents=True, exist_ok=True)
    healthy = {
        'schema_version': 1,
        'case_id': 'ZOOKEEPER-10',
        'status': 'healthy_observed_graph_path',
        'selector': 'org.apache.zookeeper.test.ObserverMasterTest#testObserver',
        'attempt_id': result['last_dispatch_attempt_id'],
        'duration_seconds': result['duration_seconds'],
        'junit': result['healthy_junit_validation'],
        'target': {'class': 'org.apache.zookeeper.server.quorum.ObserverMaster',
                   'function': 'removeProposedPacket(long)', 'node': 'zk1',
                   'check_site': PREFIX + '@368:branch:3',
                   'throw_site': PREFIX + '@374:throw:1',
                   'check_count': len(checks), 'throw_count': len(throws)},
        'healthy_closure': {'evidence_type': 'observed_graph_path',
                            'observed_edges': audit['healthy_closure_observed_edges'],
                            'observed_path_doors': audit['healthy_observed_path_doors'],
                            'in_closure_door_sites': [
                                {'site': site, 'node': node, 'epoch': epoch, 'count': count}
                                for (site, node, epoch), count in sorted(counts.items())],
                            'sample_seq': chain,
                            'sample_event_ids': [by_seq[seq]['id'] for seq in chain],
                            'sample_correlation': by_seq[94]['correlation']},
        'artifact_sha256': artifact_hashes,
        'pristine_source_sha256': source_hashes,
        'fault_campaign_admission': False,
    }
    healthy_path = ADMISSION / 'ZOOKEEPER-10-fa5f-observer-v1-healthy.json'
    healthy_sha = dump(healthy_path, healthy)
    gap = {
        'schema_version': 1,
        'case_id': 'ZOOKEEPER-10',
        'status': 'no_target_retaining_packet_io_fault_demonstrated',
        'healthy_receipt_path': str(healthy_path.relative_to(ROOT)),
        'healthy_receipt_sha256': healthy_sha,
        'healthy_result_sha256': artifact_hashes['result'],
        'healthy_offline_audit_sha256': artifact_hashes['offline_audit'],
        'healthy_trace_raw_sha256': artifact_hashes['trial_events_raw'],
        'pristine_source_sha256': source_hashes,
        'source_findings': [
            'ObserverMaster.proposalReceived adds to proposedPkts; proposalCommitted immediately invokes removeProposedPacket before any I/O in ObserverMaster.java lines 363-377 and 410-418.',
            'Follower.processPacket handles PROPOSAL and COMMIT on its follower thread. A PROPOSAL reaches ObserverMaster.proposalReceived only after FollowerZooKeeperServer.logRequest. A COMMIT reaches ObserverMaster.proposalCommitted only after FollowerZooKeeperServer.commit.',
            'The 13 observed-path fault doors are only quorum archive readRecord/writeRecord IOException doors. In Follower.followLeader, an exception from readPacket/processPacket is caught by its outer catch, followed by closeSocket; finally stops ObserverMaster.',
            'In LearnerHandler.sendPackets, IOException from oa.writeRecord is caught at lines 371-375, closes that socket and breaks the sender loop. It does not demonstrate a target-retaining COMMIT after dropping a proposal.',
            'FollowerZooKeeperServer.commit has no checked I/O operation before ObserverMaster.proposalCommitted; its mismatch path requests system exit. The currently instrumented I/O doors do not selectively skip one queue update while preserving the same follower/ObserverMaster occurrence.',
        ],
        'pilot_fault_trials': 0,
        'full_campaign_admission': False,
        'limitation': 'This is a bounded source and healthy-trace conclusion for the current IOException door model, not a proof that no future workload or new fault model can expose a bug.',
    }
    gap_path = ADMISSION / 'ZOOKEEPER-10-fa5f-observer-v1-fault-model-gap.json'
    gap_sha = dump(gap_path, gap)
    print(json.dumps({'healthy_receipt': str(healthy_path), 'healthy_sha256': healthy_sha,
                      'gap_receipt': str(gap_path), 'gap_sha256': gap_sha}))


if __name__ == '__main__':
    main()
