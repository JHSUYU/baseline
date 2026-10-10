#!/usr/bin/env python3
"""Independently gate an HBASE-23 typed-read healthy trace; no JVM execution."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


REGION = ('org.apache.hadoop.hbase.procedure.ZKProcedureCoordinator'
          '#sendGlobalBarrierReached(Lorg/apache/hadoop/hbase/procedure/Procedure;Ljava/util/List;)V')
CHECK = REGION + '@127:branch:5'
DOOR = ('org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper'
        '#getData(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B@405:door:1')
EXCEPTION = 'org.apache.zookeeper.KeeperException$ConnectionLossException'
HANDOFF = 'hbase:ProcedureCoordinator.submitProcedure'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_events(path):
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def review(campaign):
    campaign = Path(campaign)
    trial = campaign / 'trials/r0000'
    summary = json.loads((campaign / 'result.json').read_text())
    result = json.loads((trial / 'result.json').read_text())
    audit = json.loads((campaign / 'offline-causal-audit.json').read_text())
    events = load_events(trial / 'events.jsonl.gz')
    feedback = result.get('feedback') or {}
    reasons = []

    def require(condition, message):
        if not condition:
            reasons.append(message)

    require(summary.get('case_id') == 'HBASE-23' and
            summary.get('status') == 'calibration_complete' and
            summary.get('fault_trials_completed') == 0,
            'healthy-only campaign summary failed')
    require(result.get('junit_validation', {}).get('status') == 'passed',
            'selected JUnit did not pass')
    require(result.get('site_catalog_validation', {}).get('valid') is True,
            'site catalog invalid')
    require(feedback.get('target_threw') is False, 'selected check threw')
    require(feedback.get('target_reached') is True, 'exact check absent')
    require(not feedback.get('trace_truncated'), 'trace truncated')
    require(audit.get('case_id') == 'HBASE-23' and
            audit.get('allow_local_timeline_doors') is True and
            audit.get('healthy_local_timeline_doors', 0) > 0 and
            audit.get('healthy_closure_proven') is True and
            audit.get('report_gate_passed') is True,
            'same-thread local-timeline evidence unproven')

    submits = {e.get('correlation'): e for e in events if
               e.get('type') == 'TASK_SUBMIT' and e.get('site') == HANDOFF and
               e.get('correlation')}
    claims = {e.get('correlation'): e for e in events if
              e.get('type') == 'TASK_CLAIM' and e.get('site') == HANDOFF and
              e.get('correlation')}
    tokens = {token for token in submits.keys() & claims.keys() if
              submits[token]['seq'] < claims[token]['seq']}
    require(bool(tokens), 'accepted Procedure submit/worker claim token absent')

    typed_feedback = [d for d in feedback.get('doors', []) if
                      d.get('site') == DOOR and d.get('exception_class') == EXCEPTION and
                      d.get('in_closure') is True and
                      d.get('local_timeline_evidence', {}).get('kind') == 'observed_local_timeline']
    require(bool(typed_feedback), 'typed ZooKeeper-read door absent from target closure')
    door_events = [e for e in events if e.get('type') == 'DOOR_OBSERVED' and
                   e.get('site') == DOOR and e.get('exception_class') == EXCEPTION]
    regions = [e for e in events if e.get('type') == 'REGION_ENTER' and
               e.get('site') == REGION and str(e.get('node', '')).startswith('zk-coordinator:') and
               e.get('parent_id') in tokens]
    checks = [e for e in events if e.get('type') == 'TARGET_CHECK' and
              e.get('site') == CHECK and str(e.get('node', '')).startswith('zk-coordinator:')]
    require(bool(regions), 'named exact region lacks worker-token parent')
    require(bool(checks), 'named exact target event absent')

    matched = []
    feedback_evidence = {d.get('event_id'): d.get('local_timeline_evidence')
                         for d in typed_feedback}
    audit_samples = {(row.get('door_event_id'), row.get('target_check_event_id'))
                     for row in audit.get('healthy_local_timeline_evidence_sample', [])}
    for region in regions:
        token = region['parent_id']
        if not (submits[token]['seq'] < claims[token]['seq'] < region['seq']):
            continue
        for check in checks:
            if check.get('occurrence') != region.get('occurrence') or check.get('node') != region.get('node'):
                continue
            for door in door_events:
                evidence = feedback_evidence.get(door.get('id'))
                if (evidence is not None and
                    evidence.get('door_event_id') == door.get('id') and
                    evidence.get('target_check_event_id') == check.get('id') and
                    (door.get('id'), check.get('id')) in audit_samples and
                    door.get('occurrence') == region.get('occurrence') and
                    door.get('node') == region.get('node') and
                    isinstance(door.get('thread_id'), int) and
                    not isinstance(door.get('thread_id'), bool) and
                    door.get('thread_id') == check.get('thread_id') == region.get('thread_id') and
                    region['seq'] < door['seq'] < check['seq']):
                    matched.append({'task_token': token, 'region_event': region['id'],
                                    'door_event': door['id'], 'check_event': check['id'],
                                    'node': check['node'], 'occurrence': check['occurrence']})
    require(bool(matched), 'no same-thread, same-occurrence event-time door-to-check witness')
    return {
        'case_id': 'HBASE-23', 'status': 'healthy_admitted' if not reasons else 'healthy_not_admitted',
        'jvm_workloads_started_by_verifier': 0, 'campaign': str(campaign),
        'result_sha256': sha(campaign / 'result.json'),
        'trial_sha256': sha(trial / 'result.json'),
        'events_sha256': sha(trial / 'events.jsonl.gz'),
        'audit_sha256': sha(campaign / 'offline-causal-audit.json'),
        'typed_door': DOOR, 'exact_check': CHECK,
        'evidence_kind': 'observed_local_timeline',
        'strict_graph_path_doors': audit.get('healthy_observed_path_doors', 0),
        'matched_witnesses': matched, 'reasons': reasons,
        'fault_trials_admitted': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('campaign', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    receipt = review(args.campaign)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + '\n'
    if args.out:
        args.out.write_text(rendered)
    print(rendered, end='')
    raise SystemExit(0 if receipt['status'] == 'healthy_admitted' else 1)
