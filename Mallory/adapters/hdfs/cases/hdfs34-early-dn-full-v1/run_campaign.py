#!/usr/bin/env python3
"""Run HDFS-34 with a fresh, exact event-path admission gate."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

BASE = Path('/users/ZhenyuLi/baseline')
HERE = Path(__file__).resolve().parent
CONFIG = HERE / 'HDFS-34-node2-full-v1.json'
OUTPUT = Path('/tmp/mallory-hdfs34-early-dn-v3-node2-full')
CORE = BASE / 'Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f'
sys.path[:0] = [str(CORE), str(BASE)]

from Mallory.core import campaign  # noqa: E402
from Mallory.core.events import Trace, event_seq  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_healthy_result(result: dict, config: dict, trial: Path) -> dict:
    """Prove an observed, same-DataNode versionRequest-to-check path."""
    evidence = result.get('events_evidence', {})
    compressed = trial / evidence.get('gzip_path', 'events.jsonl.gz')
    raw = gzip.decompress(compressed.read_bytes())
    if (sha_bytes(raw) != result.get('events_sha256') or
            sha_bytes(raw) != evidence.get('raw_sha256') or
            sha_bytes(compressed.read_bytes()) != evidence.get('gzip_sha256')):
        raise ValueError('fresh healthy trace digest mismatch')
    events = tuple(json.loads(row) for row in raw.splitlines() if row.strip())
    trace = Trace(events)
    graph = OccurrenceGraph(trace.events, reject_coarse_roots=True)
    target_site = config['target']['check_sites'][0]
    door_site = ('org.apache.hadoop.hdfs.server.datanode.BPServiceActor'
                 '#retrieveNamespaceInfo()Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;@260:door:1')
    doors = [row for row in events if row.get('type') == 'DOOR_OBSERVED' and
             row.get('site') == door_site and
             row.get('node', '').startswith('hdfs-cluster-1/dn')]
    checks = [row for row in events if row.get('type') == 'TARGET_CHECK' and
              row.get('site') == target_site and
              row.get('node', '').startswith('hdfs-cluster-1/dn') and
              row.get('outcome') == 'FALLTHROUGH']
    witnesses = []
    for door in doors:
        for check in checks:
            if (door.get('node') != check.get('node') or
                    door.get('epoch') != check.get('epoch') or
                    event_seq(door) >= event_seq(check)):
                continue
            path = graph.event_path(door, check, require_edge=True)
            if path is None:
                continue
            witnesses.append({
                'door_event_id': door['id'], 'target_event_id': check['id'],
                'node': door['node'], 'epoch': door['epoch'],
                'door_seq': event_seq(door), 'target_seq': event_seq(check),
                'edges': [{'producer_event': edge.producer_event,
                           'consumer_event': edge.consumer_event, 'kind': edge.kind}
                          for edge in path],
            })
    junit = result.get('junit_validation', {})
    catalog = result.get('site_catalog_validation', {})
    feedback = result.get('feedback', {})
    passed = bool(
        result.get('trial_id') == 0 and result.get('case_id') == 'HDFS-34' and
        result.get('plan') == [] and result.get('return_code') == 0 and
        junit.get('status') == 'passed' and junit.get('tests') == 1 and
        junit.get('failures') == 0 and junit.get('errors') == 0 and
        catalog.get('valid') is True and
        catalog.get('observed_target_class_sha256') ==
        config['expected_target_class_sha256'] and
        feedback.get('status') == 'observed' and
        feedback.get('target_reached') is True and
        feedback.get('target_threw') is False and
        feedback.get('target_identity_complete') is True and
        feedback.get('target_region_present') is True and
        len(witnesses) >= 1)
    return {'schema_version': 1, 'case_id': 'HDFS-34', 'trial_id': 0,
            'passed': passed, 'fresh_result_sha256': sha_bytes(
                (trial / 'result.json').read_bytes()),
            'trace_sha256': result['events_sha256'],
            'junit_status': junit.get('status'),
            'target_class_sha256': catalog.get('observed_target_class_sha256'),
            'typed_named_doors': len(doors), 'named_exact_checks': len(checks),
            'same_actor_event_paths': len(witnesses),
            'observed_path_sample': witnesses[:10],
            'graph_gaps': graph.summary()['gaps']}


def main() -> int:
    config = campaign.read_json(CONFIG)
    original = campaign._apply_result

    def apply_with_gates(state: dict, current_config: dict, result: dict,
                         item: dict | None) -> None:
        trial_id = result['trial_id']
        if trial_id == 0:
            trial = Path(state['out']) / 'trials/r0000'
            gate = verify_healthy_result(result, current_config, trial)
            original(state, current_config, result, item)
            gate['fresh_result_sha256'] = sha_bytes((trial / 'result.json').read_bytes())
            campaign.atomic_json(Path(state['out']) / 'healthy-gate.json', gate)
            if not gate['passed']:
                state['status'] = 'healthy_event_path_unverified'
                state['queue'].clear()
            return

        # The pinned controller only mutates a fault sequence after every
        # physical fault matches/applies with the exact runtime identity and
        # a later target check remains. Verify its admission behavior here.
        before = {row['signature'] for row in state['queue']}
        original(state, current_config, result, item)
        feedback = result['feedback']
        retained = (feedback.get('all_faults_effective') is True and
                    feedback.get('fault_identity_valid') is True and
                    feedback.get('target_reached') is True and
                    feedback.get('target_identity_complete') is True and
                    feedback.get('target_region_present') is True)
        after = {row['signature'] for row in state['queue']}
        generated = len(after - before)
        if not retained and generated:
            raise RuntimeError('controller expanded a non-retaining fault trial')
        campaign.atomic_json(Path(state['out']) / 'trials' /
                             f'r{trial_id:04d}' / 'postfault-gate.json', {
            'schema_version': 1, 'case_id': 'HDFS-34', 'trial_id': trial_id,
            'faults_effective': feedback.get('all_faults_effective'),
            'fault_identity_valid': feedback.get('fault_identity_valid'),
            'target_retained_after_fault': feedback.get('target_reached'),
            'eligible_to_expand': retained, 'generated_sequences': generated,
        })

    campaign._apply_result = apply_with_gates
    state = campaign.run(CONFIG, OUTPUT)
    print(json.dumps({'case_id': 'HDFS-34', 'status': state['status'],
                      'completed_trials': len(state['completed_trials'])}, sort_keys=True))
    return 0 if state['status'] in {'budget_exhausted', 'queue_exhausted'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
