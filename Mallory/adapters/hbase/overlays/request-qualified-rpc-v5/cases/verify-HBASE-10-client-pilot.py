#!/usr/bin/env python3
"""Recheck the bounded HBASE-10 fault, client retry, and exact target path."""

import argparse
import copy
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

BASE = Path('/users/ZhenyuLi/baseline')
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6')
CORE = '4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4'
sys.path[:0] = [str(BASE / 'Mallory/dispatch/releases' / CORE), str(BASE)]
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

CAMPAIGN = BASE / 'data/mallory/pilots/HBASE-10-client-scoped-v2'
RECEIPT = CAMPAIGN.parent / 'HBASE-10-client-scoped-v2-precision-positive-receipt.json'
PORT = 'hbase.pb.MasterService.UnassignRegion'
CHECK = ('org.apache.hadoop.hbase.master.assignment.AssignmentManager'
         '#preTransitCheck(Lorg/apache/hadoop/hbase/master/assignment/RegionStateNode;'
         '[Lorg/apache/hadoop/hbase/master/RegionState$State;)V@755:branch:1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique(events, predicate, label):
    matches = [event for event in events if predicate(event)]
    if len(matches) != 1:
        raise ValueError(f'{label}: expected exactly one event, observed {len(matches)}')
    return matches[0]


def verify(tamper_check=False):
    config = json.loads((CAMPAIGN / 'config.json').read_text())
    result = json.loads((CAMPAIGN / 'result.json').read_text())
    audit = json.loads((CAMPAIGN / 'offline-causal-audit.json').read_text())
    trial = json.loads((CAMPAIGN / 'trials/r0001/result.json').read_text())
    if (config['core_release']['release_id'] != CORE
            or config['budget'] != {'trials': 4, 'seconds': 900,
                                    'max_faults_per_trial': 1,
                                    'trial_timeout_seconds': 600}
            or result['status'] != 'queue_exhausted'
            or result['fault_trials_completed'] != 1
            or result['strict_injected_trials'] != 1
            or result['exact_exception_trials'] != 0
            or trial['junit_validation']['status'] != 'passed'
            or not audit['report_gate_passed']
            or not audit['guidance_consistent']
            or audit['named_applied_faults'] != 1):
        raise ValueError('terminal campaign, JUnit, or frozen audit differs')
    with gzip.open(CAMPAIGN / 'trials/r0001/events.jsonl.gz', 'rt') as source:
        events = [json.loads(line) for line in source]
    fault = unique(events, lambda e: e.get('type') == 'FAULT_APPLIED'
                   and e.get('site', '').endswith(':rpc:' + PORT), 'applied typed fault')
    response = unique(events, lambda e: e.get('type') == 'SEND'
                      and e.get('site') == 'hbase:RpcServer.call:completion'
                      and e.get('correlation') == fault['context'], 'faulted response')
    client_receive = unique(events, lambda e: e.get('type') == 'RECV'
                            and e.get('site') == 'hbase:RpcConnection.readResponse'
                            and e.get('correlation') == fault['context'], 'client response')
    retry_send = unique(events, lambda e: e.get('type') == 'SEND'
                        and e.get('site') == 'hbase:Call.<init>' and e.get('port') == PORT
                        and client_receive['seq'] < e['seq'] < client_receive['seq'] + 50,
                        'client retry send')
    retry_receive = unique(events, lambda e: e.get('type') == 'RECV'
                           and e.get('site') == 'hbase:RpcServer.call'
                           and e.get('correlation') == retry_send['correlation']
                           and e.get('port') == PORT, 'master retry receive')
    check = unique(events, lambda e: e.get('type') == 'TARGET_CHECK'
                   and e.get('site') == CHECK
                   and e.get('context') == retry_receive['context'], 'retry target check')
    first_send = unique(events, lambda e: e.get('type') == 'SEND'
                        and e.get('port') == PORT
                        and e.get('correlation') == fault['context']
                        and e.get('site') == 'hbase:Call.<init>'
                        and e['seq'] < fault['seq'], 'first client send')
    if not (first_send['seq'] < fault['seq'] < response['seq']
            < client_receive['seq'] < retry_send['seq'] < retry_receive['seq']
            < check['seq']):
        raise ValueError('request, fault, response, retry, and target are out of order')
    if (first_send['node'] != 'client' or client_receive['node'] != 'client'
            or retry_send['node'] != 'client' or fault['node'] != 'master0'
            or retry_receive['node'] != 'master0' or check['node'] != 'master0'
            or first_send['thread_id'] != retry_send['thread_id']
            or first_send['occurrence'] != retry_send['occurrence']
            or retry_receive['context'] != retry_send['correlation']
            or fault['context'] == retry_send['correlation']):
        raise ValueError('client or master actor and retry identity differ')
    client_calls = [e for e in events if e.get('type') == 'SEND'
                    and e.get('port') == PORT and e.get('node') == 'client'
                    and e['seq'] <= check['seq']]
    if [e['id'] for e in client_calls] != [first_send['id'], retry_send['id']]:
        raise ValueError('an additional client UnassignRegion call makes the retry ambiguous')
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    path = graph.event_path(fault, check, require_edge=True)
    if path is None or [edge.kind for edge in path] != [
            'rpc', 'task', 'rpc', 'region_parent', 'program_order']:
        raise ValueError('strict fault-to-retry target graph path is absent or differs')
    expected_pairs = [(response['id'], client_receive['id']),
                      ('HBASE-10-r0001:907', 'HBASE-10-r0001:908'),
                      (retry_send['id'], retry_receive['id'])]
    if [(edge.producer_event, edge.consumer_event) for edge in path[:3]] != expected_pairs:
        raise ValueError('RPC response, task handoff, or retry RPC edge differs')
    if tamper_check:
        for event_id, key in [(response['id'], 'correlation'),
                              ('HBASE-10-r0001:907', 'correlation'),
                              (retry_send['id'], 'correlation')]:
            changed = copy.deepcopy(events)
            next(e for e in changed if e['id'] == event_id)[key] = 'tampered-token'
            changed_fault = next(e for e in changed if e['id'] == fault['id'])
            changed_check = next(e for e in changed if e['id'] == check['id'])
            if OccurrenceGraph(changed, reject_coarse_roots=True).event_path(
                    changed_fault, changed_check, require_edge=True) is not None:
                raise ValueError(f'tampered {event_id} still has a claimed path')
    source_paths = {
        'junit': SOURCE / 'hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/TestRegionMove.java',
        'admin': SOURCE / 'hbase-client/src/main/java/org/apache/hadoop/hbase/client/HBaseAdmin.java',
        'retry': SOURCE / 'hbase-client/src/main/java/org/apache/hadoop/hbase/client/RpcRetryingCallerImpl.java',
    }
    files = {str(p.relative_to(CAMPAIGN)): sha(p)
             for p in sorted(CAMPAIGN.rglob('*')) if p.is_file() and p.name != '.campaign.lock'}
    receipt = {
        'schema_version': 1, 'case_id': 'HBASE-10',
        'kind': 'bounded_client_bound_fault_retry_target_positive',
        'terminal_status': result['status'],
        'duration_seconds': result['duration_seconds'],
        'fault_trials_completed': 1, 'applied_faults': 1,
        'strict_postfault_target_paths': 1, 'exact_selected_exceptions': 0,
        'new_bug': False,
        'faulted_junit': trial['junit_validation']['marker'],
        'first_request_token': fault['context'],
        'retry_request_token': retry_send['correlation'],
        'event_ids': {'first_client_send': first_send['id'], 'fault': fault['id'],
                      'response_send': response['id'], 'client_receive': client_receive['id'],
                      'retry_client_send': retry_send['id'],
                      'retry_master_receive': retry_receive['id'],
                      'retry_target_check': check['id']},
        'event_seq': {'first_client_send': first_send['seq'], 'fault': fault['seq'],
                      'response_send': response['seq'], 'client_receive': client_receive['seq'],
                      'retry_client_send': retry_send['seq'],
                      'retry_master_receive': retry_receive['seq'],
                      'retry_target_check': check['seq']},
        'client_thread_id': retry_send['thread_id'],
        'client_occurrence': retry_send['occurrence'],
        'fault_actor': {'node': fault['node'], 'epoch': fault['epoch'],
                        'thread_id': fault['thread_id'], 'occurrence': fault['occurrence']},
        'target_actor': {'node': check['node'], 'epoch': check['epoch'],
                         'thread_id': check['thread_id'], 'occurrence': check['occurrence']},
        'event_time_path': [asdict(edge) for edge in path],
        'source_sha256': {name: sha(path) for name, path in source_paths.items()},
        'source_interpretation': ('TestRegionMove has one Admin.unassign invocation; '
                                  'HBaseAdmin executes one MasterCallable through '
                                  'RpcRetryingCaller.callWithRetries. The same JUnit client '
                                  'thread sends the first and retry UnassignRegion RPCs. '
                                  'The exact selected HBaseIOException was not thrown.'),
        'core_release_id': CORE,
        'files': files,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(RECEIPT, sha(RECEIPT))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tamper-check', action='store_true')
    verify(parser.parse_args().tamper_check)
