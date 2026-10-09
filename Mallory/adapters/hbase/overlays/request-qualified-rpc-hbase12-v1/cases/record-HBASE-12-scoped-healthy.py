#!/usr/bin/env python3
"""Bind a healthy HBASE-12 seed to its observed, request-scoped causal path."""

import gzip
import hashlib
import json
from pathlib import Path

BASE = Path('/users/ZhenyuLi/baseline')
OVERLAY = BASE / 'Mallory/adapters/hbase/overlays/request-qualified-rpc-hbase12-v1'
CAMPAIGN = BASE / 'data/mallory/calibration_hbase12_scoped_graph_v1/HBASE-12'
OUT = CAMPAIGN.parent / 'HBASE-12-scoped-graph-healthy-receipt.json'
CORE = '4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4'
PORT = 'hbase.pb.MasterService.UnassignRegion'
TARGET = ('org.apache.hadoop.hbase.master.assignment.AssignmentManager'
          '#preTransitCheck(Lorg/apache/hadoop/hbase/master/assignment/RegionStateNode;'
          '[Lorg/apache/hadoop/hbase/master/RegionState$State;)V@762:branch:3')
THROW = TARGET.split('@')[0] + '@763:throw:1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one(events, predicate, label):
    selected = [event for event in events if predicate(event)]
    if len(selected) != 1:
        raise ValueError(f'{label}: expected one, found {len(selected)}')
    return selected[0]


def main():
    config = json.loads((CAMPAIGN / 'config.json').read_text())
    result = json.loads((CAMPAIGN / 'result.json').read_text())
    audit = json.loads((CAMPAIGN / 'offline-causal-audit.json').read_text())
    if (config['case_id'] != 'HBASE-12' or config['core_release']['release_id'] != CORE
            or not config['calibration_only'] or not config['require_event_time_paths']
            or config['allow_local_timeline_doors']):
        raise ValueError('wrong case, core, or causal-audit mode')
    if (result['status'] != 'calibration_complete' or not result['healthy_seed_valid']
            or result['healthy_junit_validation']['status'] != 'passed'
            or result['exact_exception_trials'] != 0):
        raise ValueError('unhealthy selected JUnit or target exception')
    if (not audit['report_gate_passed'] or not audit['guidance_consistent']
            or not audit['healthy_target_nonthrowing']
            or audit['healthy_observed_path_doors'] != 1):
        raise ValueError('strict graph-order audit failed')
    with gzip.open(CAMPAIGN / 'trials/r0000/events.jsonl.gz', 'rt') as source:
        events = [json.loads(line) for line in source]
    ids = {event['id']: event for event in events}
    witness = audit['healthy_event_time_path_sample']
    if len(witness) != 1 or len(witness[0]['edges']) != 1:
        raise ValueError('expected one exact observed program-order path')
    edge = witness[0]['edges'][0]
    if (edge['kind'] != 'program_order'
            or edge['producer_event'] != witness[0]['door_event_id']
            or edge['consumer_event'] not in ids):
        raise ValueError('unexpected observed edge')
    door = ids[witness[0]['door_event_id']]
    child = ids[edge['consumer_event']]
    check = ids[witness[0]['target_check_event_id']]
    parent = one(events, lambda e: e.get('type') == 'REGION_ENTER'
                 and e.get('occurrence') == door['occurrence'], 'RPC parent region')
    response = one(events, lambda e: e.get('type') == 'SEND'
                   and e.get('site') == 'hbase:RpcServer.call:completion'
                   and e.get('occurrence') == door['occurrence']
                   and e.get('port') == PORT, 'RPC response')
    parent_exit = one(events, lambda e: e.get('type') == 'REGION_EXIT'
                      and e.get('occurrence') == door['occurrence'], 'RPC parent exit')
    if (door['type'] != 'DOOR_OBSERVED' or not door['site'].endswith(':rpc:' + PORT)
            or child['type'] != 'REGION_ENTER'
            or child['parent_id'] != door['occurrence']
            or check['type'] != 'TARGET_CHECK' or check['site'] != TARGET
            or check['occurrence'] != child['occurrence']
            or not parent['seq'] < door['seq'] < child['seq'] < check['seq']
            < response['seq'] < parent_exit['seq']):
        raise ValueError('target path or balanced region order mismatch')
    actor = (door['node'], door['epoch'], door['thread_id'], door['context'])
    if actor[0] != 'master0' or any(
        (event['node'], event['epoch'], event['thread_id'], event['context']) != actor
        for event in (parent, child, check, response, parent_exit)
    ):
        raise ValueError('actor/thread/context changed along path')
    if any(event.get('type') == 'TARGET_THROW' and event.get('site') == THROW
           for event in events):
        raise ValueError('selected target threw in healthy run')
    files = {str(path.relative_to(CAMPAIGN)): sha(path)
             for path in sorted(CAMPAIGN.rglob('*')) if path.is_file()}
    receipt = {
        'schema_version': 1,
        'case_id': 'HBASE-12',
        'kind': 'healthy_calibration_observed_event_time_path',
        'status': 'healthy_strict_path_verified_fault_pilot_pending',
        'duration_seconds': result['duration_seconds'],
        'junit': result['healthy_junit_validation']['marker'],
        'core_release_id': CORE,
        'named_actor': actor[0],
        'epoch': actor[1],
        'thread_id': actor[2],
        'request_context': actor[3],
        'selected_rpc_port': PORT,
        'selected_door_site': door['site'],
        'selected_target_site': TARGET,
        'event_ids': {'parent_region_enter': parent['id'], 'door': door['id'],
                      'child_region_enter': child['id'], 'target_check': check['id'],
                      'response_send': response['id'], 'parent_region_exit': parent_exit['id']},
        'event_seq': {'parent_region_enter': parent['seq'], 'door': door['seq'],
                      'child_region_enter': child['seq'], 'target_check': check['seq'],
                      'response_send': response['seq'], 'parent_region_exit': parent_exit['seq']},
        'observed_edge': edge,
        'observed_path_doors': 1,
        'audit_report_gate_passed': True,
        'files': files,
        'overlay_jar_sha256': sha(OVERLAY / 'releases/d02c2cb7ebace550/adapter.jar'),
        'input_config_sha256': sha(OVERLAY / 'cases/HBASE-12.scoped-healthy.json'),
    }
    OUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(OUT, sha(OUT))


if __name__ == '__main__':
    main()
