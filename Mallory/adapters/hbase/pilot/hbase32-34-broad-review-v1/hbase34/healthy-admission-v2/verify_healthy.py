#!/usr/bin/env python3
"""Verify named pretarget I/O and the selected nonthrowing guard offline."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = ('org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager'
          '#retrievePassword(Lorg/apache/hadoop/hbase/security/token/'
          'AuthenticationTokenIdentifier;)[B@159:branch:7')
THROW = ('org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager'
         '#retrievePassword(Lorg/apache/hadoop/hbase/security/token/'
         'AuthenticationTokenIdentifier;)[B@160:throw:1')
DOOR = ('org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper'
        '#exists(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)'
        'Lorg/apache/zookeeper/data/Stat;@250:door:1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def named_numeric(node, prefix):
    if not isinstance(node, str) or not node.startswith(prefix):
        return False
    try:
        return int(node[len(prefix):]) > 0
    except ValueError:
        return False


def main(campaign):
    summary_path = campaign / 'result.json'
    trial_path = campaign / 'trials/r0000/result.json'
    trace_path = campaign / 'trials/r0000/events.jsonl.gz'
    audit_path = campaign / 'offline-causal-audit.json'
    output_config = campaign / 'config.json'
    for path in (summary_path, trial_path, trace_path, output_config):
        if not path.is_file():
            raise SystemExit(f'missing healthy evidence: {path}')
    summary = json.loads(summary_path.read_text())
    trial = json.loads(trial_path.read_text())
    config = json.loads((HERE / 'healthy.json').read_text())
    audit = json.loads(audit_path.read_text()) if audit_path.is_file() else {}
    expected_gzip_sha = trial.get('events_evidence', {}).get('gzip_sha256')
    reasons = []
    if json.loads(output_config.read_text()) != config:
        reasons.append('campaign_config_differs_from_pinned_healthy_config')
    if expected_gzip_sha != sha(trace_path):
        reasons.append('trace_sha_mismatch')
    if summary.get('case_id') != 'HBASE-34' or summary.get('cluster_test') != config['cluster_test']:
        reasons.append('wrong_case_or_junit')
    if summary.get('fault_trials_completed') != 0:
        reasons.append('not_healthy_only')
    junit = trial.get('junit_validation') or {}
    if not (junit.get('status') == 'passed' and junit.get('tests') == 2 and
            junit.get('succeeded') == 2 and junit.get('failures') == 0 and
            junit.get('errors') == 0 and junit.get('skipped') == 0 and
            trial.get('return_code') == 0):
        reasons.append('selected_parameterized_junit_not_2_of_2_passing')
    with gzip.open(trace_path, 'rt') as stream:
        events = [json.loads(line) for line in stream]
    checks = [e for e in events if e.get('type') == 'BRANCH' and
              e.get('site') == TARGET and e.get('outcome') == 'TAKEN']
    all_target_checks = [e for e in events if e.get('type') == 'BRANCH' and
                         e.get('site') == TARGET]
    target_throws = [e for e in events if e.get('site') == THROW]
    doors = [e for e in events if e.get('type') == 'DOOR_OBSERVED' and
             e.get('site') == DOOR and
             e.get('exception_class') ==
             'org.apache.zookeeper.KeeperException$ConnectionLossException']
    named_checks = [e for e in checks if named_numeric(e.get('node'), 'token-keyseq-')]
    named_doors = [e for e in doors if named_numeric(e.get('node'), 'zk-session-')]
    pairs = [{'door_id': d.get('id'), 'door_seq': d['seq'],
              'door_node': d['node'], 'door_epoch': d.get('epoch'),
              'check_id': c.get('id'), 'check_seq': c['seq'],
              'target_node': c['node'], 'target_epoch': c.get('epoch')}
             for d in named_doors for c in named_checks if d['seq'] < c['seq']]
    if len(checks) < 2 or len(all_target_checks) != len(checks) or target_throws:
        reasons.append('selected_nonthrowing_guard_not_reached_twice')
    if len(named_checks) != len(checks):
        reasons.append('target_identity_not_named_numeric')
    if not named_doors:
        reasons.append('named_typed_zookeeper_exists_door_missing')
    if not pairs:
        reasons.append('named_door_not_before_named_target')
    receipt = {
        'schema_version': 1, 'case_id': 'HBASE-34',
        'source_runtime_admitted': not reasons,
        'rejection_reasons': reasons,
        'core_status': summary.get('status'),
        'core_healthy_seed_valid': summary.get('healthy_seed_valid'),
        'core_full_campaign_ready': bool(summary.get('healthy_seed_valid') and
                                         (summary.get('runtime_attestation') or {}).get('valid') and
                                         (summary.get('healthy_eligible_doors') or 0) > 0),
        'selected_junit': config['cluster_test'],
        'junit_tests': junit.get('tests'), 'junit_succeeded': junit.get('succeeded'),
        'selected_nonthrowing_checks': [{'id': e.get('id'), 'seq': e['seq'],
                                         'node': e.get('node'), 'epoch': e.get('epoch')}
                                        for e in checks],
        'named_typed_exists_doors': [{'id': e.get('id'), 'seq': e['seq'],
                                      'node': e.get('node'), 'epoch': e.get('epoch')}
                                     for e in named_doors],
        'named_pretarget_pairs': pairs,
        'healthy_observed_path_doors': audit.get('healthy_observed_path_doors'),
        'healthy_local_timeline_doors': audit.get('healthy_local_timeline_doors'),
        'causal_graph_path_proven': bool(audit.get('healthy_observed_path_doors', 0)),
        'interpretation': 'Named ZooKeeper session and token manager key sequence are distinct actor labels. Event order establishes pretarget I/O, not a causal graph edge.',
        'sha256': {'healthy_config': sha(HERE / 'healthy.json'),
                   'campaign_config': sha(output_config),
                   'result': sha(summary_path), 'trial_result': sha(trial_path),
                   'trace_gzip': sha(trace_path),
                   'audit': sha(audit_path) if audit_path.is_file() else None},
    }
    out = campaign / 'healthy-admission-v2.json'
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'receipt': str(out), 'source_runtime_admitted': not reasons,
                      'core_full_campaign_ready': receipt['core_full_campaign_ready'],
                      'rejection_reasons': reasons}, sort_keys=True))
    if reasons:
        raise SystemExit(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--campaign', type=Path, required=True)
    main(parser.parse_args().campaign)
