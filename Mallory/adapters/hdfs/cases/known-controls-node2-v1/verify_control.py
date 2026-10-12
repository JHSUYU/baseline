#!/usr/bin/env python3
"""Read-only healthy admission and conservative HDFS-54/55 trial review."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def events_for(trial: Path, result: dict):
    evidence = result['events_evidence']
    path = trial / evidence['gzip_path']
    if sha(path) != evidence['gzip_sha256']:
        raise RuntimeError(f'event archive SHA mismatch: {path}')
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def sites(case: str):
    if case == 'HDFS-54':
        base = 'org.apache.hadoop.hdfs.FileChecksumHelper$StripedFileNonStripedChecksumComputer#checksumBlocks()V'
        return base + '@629:branch:4', base + '@631:throw:1', None
    if case == 'HDFS-55':
        precursor = ('org.apache.hadoop.hdfs.server.balancer.KeyManager#newDataEncryptionKey()'
                     'Lorg/apache/hadoop/hdfs/security/token/block/DataEncryptionKey;@123:branch:2')
        downstream = ('org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager'
                      '#retrieveDataEncryptionKey(I[B)[B')
        return precursor, downstream + '@555:throw:1', downstream + '@552:branch:1'
    raise ValueError(case)


def verify_healthy(case: str, output: Path, *, require_audit: bool) -> dict:
    trial = output / 'trials/r0000'
    result_path = trial / 'result.json'
    result = json.loads(result_path.read_text())
    if result['case_id'] != case or result.get('plan'):
        raise RuntimeError('not a healthy trial for this control')
    junit = result['junit_validation']
    feedback = result['feedback']
    catalog = result['site_catalog_validation']
    if (junit.get('status') != 'passed' or junit.get('tests', 0) < 1 or
            junit.get('errors') != 0 or junit.get('failures') != 0 or
            catalog.get('valid') is not True or catalog.get('class_hash_match') is not True or
            feedback.get('target_reached') is not True or feedback.get('target_threw') is not False or
            feedback.get('eligible_doors_before_target', 0) < 1 or
            not feedback.get('target_closures') or
            not all(str(row.get('node', '')).startswith(('hdfs-client', 'hdfs-cluster-'))
                    for row in feedback['target_closures'])):
        raise RuntimeError('healthy JUnit, exact site, named actor, or typed door gate failed')
    precursor, throw, downstream = sites(case)
    observed = list(events_for(trial, result))
    checks = [row for row in observed if row.get('type') == 'TARGET_CHECK']
    throws = [row for row in observed if row.get('type') == 'TARGET_THROW']
    doors = [row for row in observed if row.get('type') == 'DOOR_OBSERVED'
             and row.get('exception_class') == 'java.io.IOException']
    if not any(row.get('site') == precursor for row in checks):
        raise RuntimeError('selected guard absent from healthy trace')
    if downstream and not any(row.get('site') == downstream and
                              str(row.get('node', '')).startswith('hdfs-cluster-')
                              for row in checks):
        raise RuntimeError('distinct DN allKeys guard absent from healthy trace')
    if any(row.get('site') == throw for row in throws) or not doors:
        raise RuntimeError('selected exception in healthy trace or no real typed I/O door')
    audit = None
    if require_audit:
        audit_path = output / 'offline-causal-audit.json'
        if not audit_path.is_file():
            raise RuntimeError('offline causal audit is required before full campaign')
        audit = json.loads(audit_path.read_text())
        if (audit.get('case_id') != case or audit.get('report_gate_passed') is not True or
                audit.get('healthy_observed_path_doors', 0) < 1 or
                audit.get('campaign_result_sha256') != sha(output / 'result.json')):
            raise RuntimeError('healthy offline causal report gate failed')
    return {'case_id': case, 'status': 'healthy_admitted',
            'result_sha256': sha(result_path), 'junit_tests': junit['tests'],
            'selected_guard_events': sum(row.get('site') == precursor for row in checks),
            'downstream_guard_events': sum(row.get('site') == downstream for row in checks)
            if downstream else None,
            'typed_io_doors': len(doors),
            'offline_audit_sha256': sha(output / 'offline-causal-audit.json') if audit else None,
            'key_id_linkage_verified': False if case == 'HDFS-55' else None}


def review_trial(case: str, trial: Path) -> dict:
    result = json.loads((trial / 'result.json').read_text())
    if result['case_id'] != case or not result.get('plan'):
        raise RuntimeError('not a fault trial for this control')
    observed = list(events_for(trial, result))
    precursor, throw, downstream = sites(case)
    checks = [row for row in observed if row.get('type') == 'TARGET_CHECK']
    throws = [row for row in observed if row.get('type') == 'TARGET_THROW']
    guard = any(row.get('site') == precursor for row in checks)
    dn_guard = any(row.get('site') == downstream for row in checks) if downstream else None
    exact = any(row.get('site') == throw and
                row.get('exception_class') == result['feedback'].get('target_exception_class',
                 'org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException'
                 if case == 'HDFS-55' else 'org.apache.hadoop.fs.PathIOException')
                for row in throws)
    feedback = result['feedback']
    junit = result['junit_validation']
    strict = feedback.get('all_faults_effective') is True and feedback.get('fault_identity_valid') is True
    failing = junit.get('status') == 'failed' and (junit.get('failures', 0) + junit.get('errors', 0)) > 0
    candidate = strict and guard and exact and (dn_guard if downstream else True) and failing
    return {'case_id': case, 'trial_id': result.get('trial_id'),
            'strict_faults': strict, 'selected_guard_reached': guard,
            'downstream_dn_guard_reached': dn_guard, 'exact_exception': exact,
            'junit_failed': failing, 'candidate': candidate,
            'detection_claim': False,
            'remaining_proof': ('bind KeyManager cached key ID to the rejecting DataNode key map and '
                                'show the Balancer failed without clearing/retrying that key'
                                if case == 'HDFS-55' else
                                'show the failure is not the expected all-DataNode I/O failure path')}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('HDFS-54', 'HDFS-55'), required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--healthy-output', type=Path)
    group.add_argument('--trial', type=Path)
    parser.add_argument('--require-audit', action='store_true')
    args = parser.parse_args()
    outcome = (verify_healthy(args.case, args.healthy_output, require_audit=args.require_audit)
               if args.healthy_output else review_trial(args.case, args.trial))
    print(json.dumps(outcome, sort_keys=True))


if __name__ == '__main__':
    main()
