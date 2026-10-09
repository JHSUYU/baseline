#!/usr/bin/env python3
"""Bind the scoped HBASE-10 healthy trace without claiming an audited path."""

import gzip
import hashlib
import json
from pathlib import Path

BASE = Path('/users/ZhenyuLi/baseline')
CAMPAIGN = BASE / 'data/mallory/calibration_hbase10_scoped_v3/HBASE-10'
OUT = CAMPAIGN.parent / 'HBASE-10-scoped-negative-receipt.json'
PORT = 'hbase.pb.MasterService.UnassignRegion'
DOOR_SUFFIX = ':rpc:' + PORT
TARGET = ('org.apache.hadoop.hbase.master.assignment.AssignmentManager'
          '#preTransitCheck(Lorg/apache/hadoop/hbase/master/assignment/RegionStateNode;'
          '[Lorg/apache/hadoop/hbase/master/RegionState$State;)V@755:branch:1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exactly(events, predicate, label):
    matches = [event for event in events if predicate(event)]
    if len(matches) != 1:
        raise ValueError(f'{label}: expected one event, got {len(matches)}')
    return matches[0]


def main():
    result = json.loads((CAMPAIGN / 'result.json').read_text())
    audit = json.loads((CAMPAIGN / 'offline-causal-audit.json').read_text())
    if result['status'] != 'calibration_complete' or not result['healthy_seed_valid']:
        raise ValueError('healthy seed did not complete')
    if result['healthy_junit_validation']['status'] != 'passed':
        raise ValueError('selected JUnit did not pass')
    if audit['report_gate_passed'] or audit['healthy_observed_path_doors'] != 0:
        raise ValueError('this negative receipt is stale; a new audit review is needed')
    trace = CAMPAIGN / 'trials/r0000/events.jsonl.gz'
    with gzip.open(trace, 'rt') as stream:
        events = [json.loads(line) for line in stream]
    door = exactly(events, lambda e: e.get('type') == 'DOOR_OBSERVED'
                   and e.get('site', '').endswith(DOOR_SUFFIX), 'typed door')
    parent_occurrence = door['occurrence']
    parent = exactly(events, lambda e: e.get('type') == 'REGION_ENTER'
                     and e.get('occurrence') == parent_occurrence, 'RPC region entry')
    child = exactly(events, lambda e: e.get('type') == 'REGION_ENTER'
                    and e.get('parent_id') == parent_occurrence
                    and 'preTransitCheck' in e.get('site', ''), 'target child entry')
    check = exactly(events, lambda e: e.get('type') == 'TARGET_CHECK'
                    and e.get('occurrence') == child['occurrence']
                    and e.get('site') == TARGET, 'selected target check')
    response = exactly(events, lambda e: e.get('type') == 'SEND'
                       and e.get('site') == 'hbase:RpcServer.call:completion'
                       and e.get('occurrence') == parent_occurrence
                       and e.get('port') == PORT, 'RPC response')
    parent_exit = exactly(events, lambda e: e.get('type') == 'REGION_EXIT'
                          and e.get('occurrence') == parent_occurrence, 'RPC region exit')
    if not parent['seq'] < door['seq'] < child['seq'] < check['seq'] < response['seq'] < parent_exit['seq']:
        raise ValueError('nested event order is invalid')
    identity = (door['node'], door['epoch'], door['thread_id'], door['context'])
    if identity[0] == 'unknown' or any(
        (e['node'], e['epoch'], e['thread_id'], e['context']) != identity
        for e in (parent, child, check, response, parent_exit)
    ):
        raise ValueError('nested events differ in actor/thread/context')
    if any(e.get('type') == 'TARGET_THROW' and e.get('site', '').endswith('@757:throw:1')
           for e in events):
        raise ValueError('healthy selected target threw')
    files = {str(path.relative_to(CAMPAIGN)): sha(path)
             for path in sorted(CAMPAIGN.rglob('*')) if path.is_file()}
    overlay = BASE / 'Mallory/adapters/hbase/overlays/request-qualified-rpc-v5'
    receipt = {
        'schema_version': 1,
        'case_id': 'HBASE-10',
        'kind': 'healthy_calibration_causal_gap',
        'status': 'instrumentation_event_time_gate_gap',
        'duration_seconds': result['duration_seconds'],
        'junit': result['healthy_junit_validation']['marker'],
        'exact_target_check': TARGET,
        'named_actor': identity[0],
        'epoch': identity[1],
        'thread_id': identity[2],
        'request_context': identity[3],
        'selected_rpc_port': PORT,
        'event_ids': {name: event['id'] for name, event in (
            ('rpc_region_enter', parent), ('typed_door', door),
            ('target_region_enter', child), ('target_check', check),
            ('response_send', response), ('rpc_region_exit', parent_exit))},
        'event_seq': {name: event['seq'] for name, event in (
            ('rpc_region_enter', parent), ('typed_door', door),
            ('target_region_enter', child), ('target_check', check),
            ('response_send', response), ('rpc_region_exit', parent_exit))},
        'parent_region_occurrence': parent_occurrence,
        'child_parent_id_matches_parent_occurrence': True,
        'audit_report_gate_passed': False,
        'audit_healthy_observed_path_doors': 0,
        'gate_reason': ('fa5f region_parent producer is parent REGION_ENTER before DOOR; '
                        'event-time path does not yet prove a later event inside the '
                        'parent region to child REGION_ENTER'),
        'files': files,
        'overlay_jar_sha256': sha(next((overlay / 'releases').glob('*/adapter.jar'))),
        'input_config_sha256': sha(overlay / 'cases/HBASE-10.scoped-healthy.json'),
    }
    OUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(OUT, sha(OUT))


if __name__ == '__main__':
    main()
