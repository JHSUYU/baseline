#!/usr/bin/env python3
"""Verify the bounded pilot's exact replay and missing client-side causal edge."""

import gzip
import hashlib
import json
from pathlib import Path
import sys

BASE = Path('/users/ZhenyuLi/baseline')
CORE = '4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4'
sys.path[:0] = [str(BASE / 'Mallory/dispatch/releases' / CORE), str(BASE)]
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

CAMPAIGN = BASE / 'data/mallory/pilots/HBASE-10-scoped-graph-v1'
OUT = CAMPAIGN.parent / 'HBASE-10-scoped-graph-v1-precision-gap-receipt.json'
PORT = 'hbase.pb.MasterService.UnassignRegion'
TARGET = ('org.apache.hadoop.hbase.master.assignment.AssignmentManager'
          '#preTransitCheck(Lorg/apache/hadoop/hbase/master/assignment/RegionStateNode;'
          '[Lorg/apache/hadoop/hbase/master/RegionState$State;)V@755:branch:1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one(events, predicate, label):
    matches = [e for e in events if predicate(e)]
    if len(matches) != 1:
        raise ValueError(f'{label}: expected one, got {len(matches)}')
    return matches[0]


def main():
    config = json.loads((CAMPAIGN / 'config.json').read_text())
    result = json.loads((CAMPAIGN / 'result.json').read_text())
    audit = json.loads((CAMPAIGN / 'offline-causal-audit.json').read_text())
    if (config['core_release']['release_id'] != CORE
            or config['budget']['max_faults_per_trial'] != 1
            or result['status'] != 'queue_exhausted'
            or result['fault_trials_completed'] != 1
            or result['strict_injected_trials'] != 1
            or result['strict_target_trials'] != 1
            or result['exact_exception_trials'] != 0
            or not audit['report_gate_passed']
            or audit['same_actor_target_trials'] != 0):
        raise ValueError('pilot summary differs from expected bounded negative')
    trial = json.loads((CAMPAIGN / 'trials/r0001/result.json').read_text())
    if trial['junit_validation']['status'] != 'passed':
        raise ValueError('faulted selected JUnit did not pass')
    with gzip.open(CAMPAIGN / 'trials/r0001/events.jsonl.gz', 'rt') as source:
        events = [json.loads(line) for line in source]
    fault = one(events, lambda e: e.get('type') == 'FAULT_APPLIED'
                and e.get('site', '').endswith(':rpc:' + PORT), 'selected applied fault')
    response = one(events, lambda e: e.get('type') == 'SEND'
                   and e.get('site') == 'hbase:RpcServer.call:completion'
                   and e.get('correlation') == fault['context'], 'fault response')
    client_receive = one(events, lambda e: e.get('type') == 'RECV'
                         and e.get('site') == 'hbase:RpcConnection.readResponse'
                         and e.get('correlation') == fault['context'], 'client response')
    retry_send = one(events, lambda e: e.get('type') == 'SEND'
                     and e.get('site') == 'hbase:Call.<init>' and e.get('port') == PORT
                     and response['seq'] < e['seq'] < response['seq'] + 50,
                     'following client UnassignRegion send')
    retry_receive = one(events, lambda e: e.get('type') == 'RECV'
                        and e.get('site') == 'hbase:RpcServer.call'
                        and e.get('correlation') == retry_send['correlation']
                        and e.get('port') == PORT, 'following server receive')
    retry_check = one(events, lambda e: e.get('type') == 'TARGET_CHECK'
                      and e.get('site') == TARGET
                      and e.get('context') == retry_receive['context'],
                      'following exact target check')
    if not (fault['seq'] < response['seq'] < client_receive['seq']
            < retry_send['seq'] < retry_receive['seq'] < retry_check['seq']):
        raise ValueError('request and response order differs')
    if (fault['node'] != 'master0' or retry_receive['node'] != 'master0'
            or client_receive['node'] != 'unknown' or retry_send['node'] != 'unknown'):
        raise ValueError('named server or missing client binding differs')
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    if graph.event_path(fault, retry_check, require_edge=True) is not None:
        raise ValueError('fault-to-retry target is now proven; negative receipt is stale')
    if any(graph.event_path(fault, check, require_edge=True) is not None
           for check in events if check.get('type') == 'TARGET_CHECK'
           and check.get('site') == TARGET and check['seq'] > fault['seq']):
        raise ValueError('another strict postfault target witness exists')
    files = {str(path.relative_to(CAMPAIGN)): sha(path)
             for path in sorted(CAMPAIGN.rglob('*')) if path.is_file()}
    receipt = {
        'schema_version': 1,
        'case_id': 'HBASE-10',
        'kind': 'bounded_fault_pilot_precision_gap',
        'status': 'postfault_retry_path_unverified_client_actor_unknown',
        'core_release_id': CORE,
        'duration_seconds': result['duration_seconds'],
        'fault_trials_completed': 1,
        'applied_faults': 1,
        'aggregate_target_retained': 1,
        'strict_postfault_target_paths': 0,
        'exact_selected_exceptions': 0,
        'faulted_junit': trial['junit_validation']['marker'],
        'event_ids': {'fault': fault['id'], 'response_send': response['id'],
                      'client_receive': client_receive['id'],
                      'following_client_send': retry_send['id'],
                      'following_server_receive': retry_receive['id'],
                      'following_target_check': retry_check['id']},
        'event_seq': {'fault': fault['seq'], 'response_send': response['seq'],
                      'client_receive': client_receive['seq'],
                      'following_client_send': retry_send['seq'],
                      'following_server_receive': retry_receive['seq'],
                      'following_target_check': retry_check['seq']},
        'first_request_token': fault['context'],
        'following_request_token': retry_send['correlation'],
        'client_receive_node': client_receive['node'],
        'following_client_send_node': retry_send['node'],
        'fault_to_target_event_time_path': False,
        'files': files,
    }
    OUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(OUT, sha(OUT))


if __name__ == '__main__':
    main()
