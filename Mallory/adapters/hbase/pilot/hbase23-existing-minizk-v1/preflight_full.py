#!/usr/bin/env python3
"""No-JVM preflight for the HBASE-23 full campaign and prior seed."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from preflight import HERE, ROOT, verify as verify_healthy_package
from verify_healthy import CHECK, DOOR


PRIOR = HERE / 'prior-admitted-healthy.json'
FULL = HERE / 'full.json'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def verify(strict_runtime=False):
    base = verify_healthy_package(strict_runtime=strict_runtime)
    healthy = json.loads((HERE / 'healthy.json').read_text())
    full = json.loads(FULL.read_text())
    expected = dict(healthy)
    expected['calibration_only'] = False
    expected['auto_promote_if_healthy'] = True
    expected['budget'] = {'max_faults_per_trial': 3, 'seconds': 3600,
                          'trial_timeout_seconds': 600, 'trials': 80}
    expected['mapping'] = dict(healthy['mapping'],
                               status='full_staged_fresh_r0000_gate_pending_runtime')
    check(full == expected, 'full config differs beyond admitted budget and mode')

    import sys
    sys.path.insert(0, str(ROOT / ('Mallory/dispatch/releases/'
        'fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f')))
    from Mallory.core.campaign import validate_config
    validate_config(dict(full, cwd='/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6'))
    if strict_runtime:
        validate_config(full)

    prior = json.loads(PRIOR.read_text())
    check(prior['case_id'] == 'HBASE-23' and
          prior['selector'] == full['cluster_test'] and
          prior['observed']['exact_check'] == CHECK and
          prior['observed']['typed_door'] == DOOR and
          prior['observed']['admission_status'] == 'healthy_admitted',
          'prior seed identity or reported admission changed')
    evidence_root = Path(prior['evidence_root'])
    deferred = []
    for name, digest in prior['files_sha256'].items():
        path = evidence_root / name
        if not path.is_file():
            deferred.append(str(path))
        else:
            check(sha(path) == digest, f'prior admitted evidence digest mismatch: {path}')
    if strict_runtime:
        check(not deferred, f'prior admitted evidence absent on node1: {deferred}')
        admission = json.loads((evidence_root / 'admission-receipt.json').read_text())
        result = json.loads((evidence_root / 'result.json').read_text())
        trial = json.loads((evidence_root / 'trials/r0000/result.json').read_text())
        audit = json.loads((evidence_root / 'offline-causal-audit.json').read_text())
        check(admission['status'] == 'healthy_admitted' and
              admission['reasons'] == [] and
              len(admission['matched_witnesses']) >= 1 and
              admission['exact_check'] == CHECK and admission['typed_door'] == DOOR,
              'prior admission receipt no longer proves exact typed path')
        check(result['status'] == 'calibration_complete' and
              result['healthy_seed_valid'] is True and
              result['cluster_test'] == full['cluster_test'] and
              result['healthy_eligible_doors'] >= 1 and
              trial['feedback']['target_reached'] is True and
              trial['feedback']['target_threw'] is False and
              trial['junit_validation']['status'] == 'passed',
              'prior raw healthy seed no longer qualifies')
        check(audit['report_gate_passed'] is True and
              audit['healthy_closure_proven'] is True and
              audit['healthy_local_timeline_doors'] >= 1,
              'prior offline causal audit failed')
    return {
        'case_id': 'HBASE-23',
        'status': 'node1_full_runtime_verified' if strict_runtime else
                  'offline_full_valid_node1_runtime_deferred',
        'jvm_workloads_run': 0, 'fault_trials_run': 0,
        'full_config_sha256': sha(FULL),
        'prior_evidence_pin_sha256': sha(PRIOR),
        'prior_evidence_deferred': deferred,
        'base_runtime_deferred': base['node1_runtime_deferred'],
        'exact_check': CHECK, 'typed_door': DOOR,
        'go_gate': 'node1 dispatch only; full campaign own r0000 is checked synchronously before any fault trial',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict-runtime', action='store_true')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    receipt = verify(strict_runtime=args.strict_runtime)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + '\n'
    if args.write:
        (HERE / 'stage-full-preflight.json').write_text(rendered)
    print(rendered, end='')
