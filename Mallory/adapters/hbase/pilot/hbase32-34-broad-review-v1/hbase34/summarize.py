#!/usr/bin/env python3
"""Record natural terminal and graph quality separately; never starts a JVM."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

TARGET = 'org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager#retrievePassword(Lorg/apache/hadoop/hbase/security/token/AuthenticationTokenIdentifier;)[B@159:branch:7'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main(campaign, mode):
    summary = json.loads((campaign / 'result.json').read_text())
    trial = campaign / 'trials/r0000'
    events = []
    trace = trial / 'events.jsonl.gz'
    if trace.is_file():
        with gzip.open(trace, 'rt') as stream:
            events = [json.loads(line) for line in stream]
    checks = [e for e in events if e.get('site') == TARGET and
              e.get('type') == 'BRANCH' and e.get('outcome') == 'TAKEN']
    doors = [e for e in events if e.get('type') == 'DOOR' and
             e.get('site', '').startswith('org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper#exists(')]
    pairs = [{'door_seq': d['seq'], 'check_seq': c['seq'],
              'door_node': d.get('node'), 'check_node': c.get('node')}
             for d in doors for c in checks if d['seq'] < c['seq']]
    junit = summary.get('healthy_junit_validation') or {}
    audit_path = campaign / 'offline-causal-audit.json'
    audit = json.loads(audit_path.read_text()) if audit_path.is_file() else {}
    natural = summary.get('status') in {'budget_exhausted', 'queue_exhausted'}
    report = {
        'schema_version': 1, 'case_id': 'HBASE-34', 'mode': mode,
        'campaign_status': summary.get('status'),
        'natural_full_terminal': bool(mode == 'full' and natural),
        'fault_trials_completed': summary.get('fault_trials_completed'),
        'healthy_junit': {'status': junit.get('status'), 'tests': junit.get('tests'),
                          'succeeded': junit.get('succeeded'),
                          'failures': junit.get('failures'), 'errors': junit.get('errors')},
        'target_node_named': summary.get('target_node_named'),
        'healthy_seed_valid': summary.get('healthy_seed_valid'),
        'selected_nonthrowing_checks': [{'seq': e['seq'], 'node': e.get('node')}
                                        for e in checks],
        'typed_pretarget_doors': [{'seq': e['seq'], 'node': e.get('node')}
                                  for e in doors],
        'temporal_door_check_pairs': pairs,
        'healthy_observed_path_doors': audit.get('healthy_observed_path_doors'),
        'healthy_local_timeline_doors': audit.get('healthy_local_timeline_doors'),
        'graph_path_proven': bool(audit.get('healthy_observed_path_doors', 0)),
        'graph_quality_note': 'A temporal pair alone does not establish a same-actor or causal path. Inspect offline audit and target/door actors before claiming one.',
        'sha256': {'result': sha(campaign / 'result.json'),
                   'healthy_trial_result': sha(trial / 'result.json'),
                   'healthy_events': sha(trace),
                   'offline_causal_audit': sha(audit_path)},
    }
    path = campaign / 'case-local-verdict.json'
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--mode', choices=('healthy', 'full'), required=True)
    args = parser.parse_args()
    main(args.campaign, args.mode)
