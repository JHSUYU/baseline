#!/usr/bin/env python3
"""Mirror the separate retry-internal campaign after the v1 campaign stops."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from mirror import BASE_SECONDS, BASE_FAULT_TRIALS, CASES, HERE, PIVOT, SSH


REMOTE = ('ZhenyuLi@node2:/users/ZhenyuLi/baseline/.study-repairs/'
          'unit-test-pivot/cases/SOLR-14/independent/native/campaign/progress.json')
NATIVE_BASE_SECONDS = 21.199 + 20.377 + 25.646
NATIVE_CALIBRATION_FAULTS = 1


def atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f'.tmp.{os.getpid()}')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, path)


def sync() -> dict | None:
    target = HERE / 'native/campaign/live-progress.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('live-progress.json.rsynctmp')
    result = subprocess.run(['rsync', '-q', '-e', SSH, REMOTE, str(temporary)],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    data = json.loads(temporary.read_text())
    os.replace(temporary, target)
    return data


def publish(native: dict) -> bool:
    main = json.loads((HERE / 'campaign/live-progress.json').read_text())
    if main['status'] not in ('budget_complete', 'queue_exhausted'):
        return False
    if subprocess.run(['tmux', 'has-session', '-t', 'solr_split_mirror80_v2'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      check=False).returncode == 0:
        return False
    chaos_audit = HERE / 'supplemental/shardsplit/native-chaos-fault-02/audit.json'
    chaos = json.loads(chaos_audit.read_text()) if chaos_audit.exists() else None
    review_path = HERE / 'supplemental/shardsplit/solr15-native-candidate-source-review.json'
    review = json.loads(review_path.read_text()) if review_path.exists() else None
    for number in (14, 15, 16):
        case = f'SOLR-{number:02d}'
        path = CASES / case / 'result.json'
        row = json.loads(path.read_text())
        chaos_check = (chaos['target_outcomes'][case]['post_fault_final_check']
                       if chaos and chaos['strict_injection'] else 0)
        chaos_throw = (chaos['target_outcomes'][case]['post_fault_exact_throw']
                       if chaos and chaos['strict_injection'] else 0)
        throws = (main['target_exception_after_fault_trials'][case]
                  + native['target_exception_after_fault_trials'][case]
                  + chaos_throw)
        row.update({
            'fault_trials': (BASE_FAULT_TRIALS + main['fault_trials']
                             + NATIVE_CALIBRATION_FAULTS + native['fault_trials']),
            'strict_injections': (BASE_FAULT_TRIALS + main['strict_injections']
                                  + NATIVE_CALIBRATION_FAULTS + native['strict_injections']),
            'target_after_fault': (main['post_fault_target_reach_trials'][case]
                                   + (1 if number == 14 else 0)
                                   + native['post_fault_target_reach_trials'][case]
                                   + chaos_check),
            'target_exception_after_fault_trials': throws,
            'supplemental_native_chaos_target': {
                'fault_trials': 2 if chaos else 1,
                'strict_injections': 2 if chaos and chaos['strict_injection'] else 1,
                'post_fault_final_check': chaos_check,
                'post_fault_exact_throw': chaos_throw,
                'evidence': 'SOLR-14/independent/supplemental/shardsplit/native-chaos-fault-02/audit.json'
                            if chaos else 'SOLR-14/independent/supplemental/shardsplit/native-chaos-fault-01/audit.json',
            },
            'target_exception_source_review': (
                {'classification': review['classification'],
                 'evidence': 'SOLR-14/independent/supplemental/shardsplit/solr15-native-candidate-source-review.json',
                 'reproductions': len(review['reproductions'])}
                if review and number == 15 else None),
            'elapsed_seconds': round(BASE_SECONDS + main['elapsed_seconds']
                                     + NATIVE_BASE_SECONDS + native['elapsed_seconds'], 3),
            'independent_native_campaign': native,
            'native_retry_calibration': {
                'original_junit_passed': True,
                'strict_applied': 1,
                'same_operation_retried': True,
                'solr14_check_after_fault': True,
                'outer_check_after_fault': True,
                'elapsed_seconds': 25.646,
                'agent_sha256': '22e2a06b0f89009d53c54f151c922b09a6d32d5be1d52d0b91b34f7edb7a6da0',
            },
            'native_production_probe_gain': native['production_probe_gain'],
            'coverage_gain': main['production_probe_gain'],
            'coverage_gain_scope': 'v1 main production probe gain; native separately in native_production_probe_gain, do not add without JaCoCo union',
            'post_fault_outer_guard_trials': (main['post_fault_outer_guard_trials']
                                               + NATIVE_CALIBRATION_FAULTS
                                               + native['post_fault_outer_guard_trials']),
            'methodology': 'coverage_io_independent_asm_jacoco',
            'quality_complete': False,
            'bug_mark': ('candidate_target_exception' if chaos_throw and not review
                         else 'none'),
            'updated_at': time.time(),
        })
        if throws and review and number == 15:
            row['status'] = ('fuzz_running_native_retry_target_exception_expected'
                             if native['status'] == 'running' else
                             'target_exception_observed_expected_abort')
            row['reason'] = ('The exact SOLR-15 throw reproduced twice after two strict '
                             'faults, but the original test intentionally stops its '
                             'parent leader. Both runs read a missing leader live znode, '
                             'mark child shards RECOVERY_FAILED, and pass the test’s '
                             'document consistency checks. Source review classifies '
                             'the throw as the expected protective abort.')
        elif throws:
            row['status'] = 'candidate_target_exception_review'
            row['reason'] = ('Two strict retry-internal ZooKeeper ConnectionLoss faults in the '
                             'unchanged multi-node chaos JUnit reached the exact SOLR-15 '
                             'line 538 protective abort; source review and replay are in progress.')
        elif native['status'] == 'running':
            row['status'] = ('fuzz_running_native_retry' if number == 14 else
                             'fuzz_running_native_retry_final_guard_not_observed')
        elif native['status'] in ('budget_complete', 'queue_exhausted'):
            row['status'] = ('retry_campaign_done_review_pending' if number == 14 else
                             'target_final_guard_not_observed_review_pending')
        elif native['status'] == 'candidate_target_exception':
            row['status'] = 'paused_shared_candidate_review'
        atomic(path, row)
    subprocess.run(['python3', str(PIVOT / 'checklist.py'), 'render'],
                   cwd=PIVOT.parents[1], check=True, stdout=subprocess.DEVNULL)
    return True


def main() -> None:
    last = None
    while True:
        if (HERE / 'native/campaign/mirror.stop').exists():
            break
        native = sync()
        if native is not None:
            digest = hashlib.sha256(json.dumps(native, sort_keys=True).encode()).hexdigest()
            if digest != last:
                if publish(native):
                    print(f"{time.strftime('%F %T')} native_trials={native['fault_trials']} "
                          f"strict={native['strict_injections']} status={native['status']}", flush=True)
                    last = digest
            if native['status'] != 'running' and last == digest:
                break
        time.sleep(10)


if __name__ == '__main__':
    main()
