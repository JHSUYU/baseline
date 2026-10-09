#!/usr/bin/env python3
"""Verify ZK12's exact applied fault and same-occurrence target continuation."""

import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path('/users/ZhenyuLi/baseline')
CAMPAIGN = ROOT / 'data/mallory/pilot_fa5f_node0/ZOOKEEPER-12-filenotfound-v1'
ADMISSION = ROOT / 'data/mallory/admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-pilot.json'
DOOR = 'org.apache.zookeeper.server.quorum.QuorumPeer#readLongFromFile(Ljava/lang/String;)J@2190:door:1'
CHECK = 'org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1193:branch:3'
EXPECTED = [(2, 3, True), (2, 2, False), (2, 1, True),
            (1, 2, True), (1, 1, True)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    result = json.loads((CAMPAIGN / 'result.json').read_text())
    audit = json.loads((CAMPAIGN / 'offline-causal-audit.json').read_text())
    config = json.loads((CAMPAIGN / 'config.json').read_text())
    assert result['status'] == 'budget_exhausted'
    assert result['fault_trials_completed'] == 5
    assert result['exact_exception_trials'] == 0
    assert audit['report_gate_passed'] and audit['trial_count'] == 6
    assert audit['campaign_result_sha256'] == sha(CAMPAIGN / 'result.json')
    assert audit['same_actor_target_trials'] == 4
    assert audit['target_retained_fault_trials'] == 4
    assert config['budget']['max_faults_per_trial'] == 1
    assert config['explore_outside_closure'] is False
    trial_rows = []
    for trial_id, (epoch, ordinal, retained) in enumerate(EXPECTED, 1):
        directory = CAMPAIGN / 'trials' / f'r{trial_id:04d}'
        trial_path = directory / 'result.json'
        trial = json.loads(trial_path.read_text())
        evidence = trial['events_evidence']
        trace_path = directory / evidence['gzip_path']
        raw = gzip.decompress(trace_path.read_bytes())
        assert sha(trace_path) == evidence['gzip_sha256']
        assert hashlib.sha256(raw).hexdigest() == evidence['raw_sha256']
        events = [json.loads(line) for line in raw.splitlines()]
        plan = trial['plan']
        assert len(plan) == 1 and plan[0]['exception_class'] == 'java.io.FileNotFoundException'
        assert plan[0]['point'] == {'site': DOOR, 'node': 'zk0',
                                    'epoch': epoch, 'door_ordinal': ordinal}
        feedback = trial['feedback']
        assert feedback['all_faults_effective'] and feedback['fault_identity_valid']
        faults = [event for event in events if event['type'] == 'FAULT_APPLIED']
        assert len(faults) == 1
        fault = faults[0]
        assert fault['fault_id'] == plan[0]['fault_id']
        assert fault['site'] == DOOR and fault['node'] == 'zk0'
        assert fault['epoch'] == epoch and fault['door_ordinal'] == ordinal
        assert fault['exception_class'] == 'java.io.FileNotFoundException'
        later = [event for event in events if event['type'] == 'TARGET_CHECK'
                 and event['site'] == CHECK and event['node'] == fault['node']
                 and event['epoch'] == fault['epoch']
                 and event['occurrence'] == fault['occurrence']
                 and event['thread_id'] == fault['thread_id']
                 and event['seq'] > fault['seq'] and event['ts'] > fault['ts']]
        assert bool(later) is retained
        assert not any(event['type'] == 'TARGET_THROW' for event in events)
        assert feedback['target_reached'] is retained
        assert trial['junit_validation']['status'] == ('passed' if retained else 'failed')
        trial_rows.append({
            'trial_id': trial_id, 'epoch': epoch, 'door_ordinal': ordinal,
            'fault_event_id': fault['id'], 'fault_seq': fault['seq'],
            'fault_occurrence': fault['occurrence'],
            'same_occurrence_target_event_ids': [event['id'] for event in later],
            'target_retained': retained,
            'junit_status': trial['junit_validation']['status'],
            'trial_result_sha256': sha(trial_path),
            'trace_gzip_sha256': sha(trace_path),
            'trace_raw_sha256': hashlib.sha256(raw).hexdigest(),
        })
    receipt = {
        'schema_version': 1,
        'case_id': 'ZOOKEEPER-12',
        'status': 'bounded_filenotfound_pilot_four_target_retained_zero_throw',
        'pilot_result_sha256': sha(CAMPAIGN / 'result.json'),
        'pilot_offline_audit_sha256': sha(CAMPAIGN / 'offline-causal-audit.json'),
        'pilot_config_sha256': sha(CAMPAIGN / 'config.json'),
        'prepared_config_sha256': sha(ROOT / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-12-fa5f-filenotfound-pilot.json'),
        'healthy_receipt_sha256': sha(ROOT / 'data/mallory/admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-healthy.json'),
        'fault_trials': 5,
        'exact_faults_applied': 5,
        'same_actor_same_occurrence_postfault_checks': 4,
        'target_exception_candidates': 0,
        'trial_evidence': trial_rows,
        'source_interpretation': [
            'Epoch2 door ordinal3 is the acceptedEpoch read: FileNotFoundException uses the locally caught fallback acceptedEpoch=epochOfZxid and reaches the same target check. The trace identifies the ordinal; the filename follows the deterministic source call order, not a recorded argument.',
            'Epoch2 ordinal2 is the currentEpoch.tmp read. Its FileNotFoundException is not locally caught and the selected target is lost, so it is not a valid retained fault path.',
            'The four retained trials preserve the selected guard but do not trigger its IOException; additional multi-fault exploration is a separate campaign with no present bug claim.',
        ],
        'full_campaign_admission': False,
    }
    ADMISSION.parent.mkdir(parents=True, exist_ok=True)
    ADMISSION.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'receipt': str(ADMISSION), 'sha256': sha(ADMISSION)}))


if __name__ == '__main__':
    main()
