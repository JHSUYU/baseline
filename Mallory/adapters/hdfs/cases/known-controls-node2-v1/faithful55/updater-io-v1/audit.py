#!/usr/bin/env python3
"""Read-only causal oracle for the naturally missing HDFS-55 DEK key."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(log: str) -> list[dict]:
    rows = []
    for index, line in enumerate(log.splitlines()):
        if not line.startswith('CASE55F '):
            continue
        body = line[len('CASE55F '):]
        fields = dict(re.findall(r'([A-Za-z_]+)=([^\s]+)', body))
        rows.append({'index': index, 'event': body.split()[0].split('=')[0], **fields})
    return rows


def one(rows: list[dict], kind: str, predicate=lambda row: True) -> dict | None:
    return next((row for row in rows if row['event'] == kind and predicate(row)), None)


def run(output: Path, name: str) -> tuple[dict, str, list[dict]]:
    folder = output / name
    manifest = json.loads((folder / 'manifest.json').read_text())
    log_path = folder / 'junit.log'
    if sha(log_path) != manifest['junit_log_sha256']:
        raise RuntimeError(f'JUnit log SHA mismatch: {name}')
    log = log_path.read_text(errors='replace')
    return manifest, log, events(log)


def junit_ok(manifest: dict, log: str) -> bool:
    return (manifest['returncode'] == 0 and 'CONTROL original_junit_runs=1' in log
            and 'CONTROL original_junit_failures=0' in log)


def same_endpoint(left: str | None, right: str | None) -> bool:
    return bool(left and right and ':' in left and ':' in right
                and left.rsplit(':', 1)[1] == right.rsplit(':', 1)[1])


def fault_witness(manifest: dict, log: str, rows: list[dict], *, fixed: bool) -> dict:
    gaps: list[str] = []
    fresh = one(rows, 'fresh_key_selected')
    manager = one(rows, 'manager_selected')
    destination = one(rows, 'destination')
    if not fresh or not manager or not destination:
        return {'witness_passed': False,
                'gaps': ['fresh_NN_key_manager_or_destination_missing']}
    key = fresh.get('key_id')
    actor = manager.get('manager')
    uuid = destination.get('uuid')
    if manager.get('key_id') != key or fresh.get('dn_uuid') != uuid:
        gaps.append('selected_key_or_destination_identity_mismatch')
    faults = [row for row in rows if row['event'] == 'updater_io_exception'
              and row.get('manager') == actor and row.get('key_id') == key
              and row.get('nn_proxy') == manager.get('nn_proxy')
              and row.get('nn_endpoint') == manager.get('nn_endpoint')
              and row.get('bpid') == manager.get('bpid')
              and row.get('actor') not in (None, 'null')]
    if not faults or any(row.get('budget_ok') != 'true' for row in faults):
        gaps.append('typed_updater_IO_or_budget_missing')
    rotations = [row for row in rows if row['event'] == 'nn_rotation']
    if (not any(row.get('current') == key for row in rotations)
            or not any(row.get('current') != key and row['index'] > fresh['index']
                       for row in rotations)):
        gaps.append('NN_promotion_and_retirement_not_observed')
    release = one(rows, 'move_release', lambda row: row.get('stale_key') == key
                  and row.get('target_uuid') == uuid and row.get('nn_has_stale') == 'false'
                  and row.get('dn_has_stale') == 'false'
                  and row.get('dn_has_current') == 'true'
                  and same_endpoint(row.get('endpoint'), destination.get('endpoint')))
    if not release:
        gaps.append('natural_prune_and_move_release_missing')
    dn_manager = release.get('dn_manager') if release else None
    if release and not any(row['event'] == 'dn_add_keys'
                           and row.get('uuid') == uuid
                           and row.get('manager') == dn_manager
                           and row['index'] < release['index'] for row in rows):
        gaps.append('DN_key_update_actor_binding_missing')
    if release and not any(row['event'] == 'dn_map_after_add'
                           and row.get('manager') == dn_manager
                           and row.get('selected_key') == key
                           and row.get('selected_present') == 'false'
                           and row['index'] < release['index'] for row in rows):
        gaps.append('actual_DN_map_prune_missing')
    decisions = [row for row in rows if row['event'] == 'key_decision'
                 and row.get('manager') == actor and row.get('key_id') == key
                 and same_endpoint(row.get('target_endpoint'), destination.get('endpoint'))]
    nonce = decisions[0].get('nonce_digest') if decisions else None
    if not decisions or nonce in (None, 'none'):
        gaps.append('Balancer_cached_key_and_nonce_missing')
    miss = one(rows, 'dn_allkeys', lambda row: row.get('manager') == dn_manager
               and row.get('dn_uuid') == uuid and row.get('key_id') == key
               and row.get('bpid') == manager.get('bpid')
               and row.get('nonce_digest') == nonce and row.get('present') == 'false'
               and same_endpoint(row.get('dn_endpoint'), row.get('peer_endpoint'))
               and release is not None and row['index'] > release['index'])
    if not miss:
        gaps.append('native_DN_allKeys_null_with_same_key_nonce_missing')
    wire = one(rows, 'dn_wire_error_response', lambda row:
               row.get('dn_wire_error_response') == 'INVALID_KEY'
               and miss is not None and same_endpoint(row.get('peer_endpoint'),
                                                       miss.get('peer_endpoint'))
               and miss is not None and row['index'] > miss['index'])
    if not wire or 'InvalidEncryptionKeyException' not in log:
        gaps.append('native_IKE_and_INVALID_KEY_wire_response_missing')
    if miss and re.search(r'InvalidBlockTokenException|InvalidToken', '\n'.join(log.splitlines()[:miss['index']])):
        gaps.append('earlier_block_token_or_SASL_failure')
    clears = [row for row in rows if row['event'] == 'balancer_key_cache_cleared']
    if fixed:
        if not junit_ok(manifest, log):
            gaps.append('fixed_JUnit_did_not_pass')
        if not clears or not wire or clears[0]['index'] <= wire['index']:
            gaps.append('fixed_foreground_clear_after_native_IKE_missing')
        fetch = one(rows, 'foreground_keys_fetched', lambda row:
                    row.get('manager') == actor and row.get('current_key') != key
                    and row.get('nn_proxy') == manager.get('nn_proxy')
                    and row.get('nn_endpoint') == manager.get('nn_endpoint')
                    and wire is not None and row['index'] > wire['index']
                    and clears and row['index'] < clears[0]['index'])
        if not fetch:
            gaps.append('fixed_successful_foreground_NN_refetch_missing')
        if not any(row['event'] == 'key_decision' and row.get('manager') == actor
                   and row.get('key_id') not in (key, 'none')
                   and same_endpoint(row.get('target_endpoint'), destination.get('endpoint'))
                   and clears and row['index'] > clears[0]['index'] for row in rows):
            gaps.append('fixed_refetch_new_key_decision_missing')
    else:
        if (manifest['returncode'] != 1 or
                not re.search(r'NO_MOVE_PROGRESS|No block has been moved|expected:<0> but was:<-3>', log)
                or 'CONTROL original_junit_failures=1' not in log):
            gaps.append('original_no_progress_JUnit_failure_missing')
        if clears:
            gaps.append('original_unexpected_cache_clear')
        reuse = [row for row in decisions if row.get('nonce_digest') == nonce
                 and row.get('refresh') == 'false']
        if len(reuse) < 2:
            gaps.append('repeated_same_manager_key_nonce_refresh_false_missing')
    return {'witness_passed': not gaps, 'gaps': gaps,
            'selected_key_id': key, 'balancer_manager': actor,
            'destination_uuid': uuid, 'dn_manager': dn_manager,
            'nonce_digest': nonce, 'updater_io_count': len(faults),
            'dn_null_guard_index': miss['index'] if miss else None,
            'wire_index': wire['index'] if wire else None}


def audit(output: Path) -> dict:
    hm, hl, hr = run(output, 'healthy')
    om, ol, orows = run(output, 'fault-original')
    fm, fl, frows = run(output, 'fault-fixed')
    healthy_gaps = []
    if not junit_ok(hm, hl): healthy_gaps.append('healthy_JUnit_not_one_pass')
    if not one(hr, 'fresh_key_selected') or not one(hr, 'manager_selected'):
        healthy_gaps.append('healthy_fresh_key_or_manager_missing')
    if any(row['event'] == 'updater_io_exception' for row in hr):
        healthy_gaps.append('healthy_updater_fault_present')
    original = fault_witness(om, ol, orows, fixed=False)
    fixed = fault_witness(fm, fl, frows, fixed=True)
    same_policy = (om['inject_updater_io'] is True
                   and fm['inject_updater_io'] is True
                   and om['wait_ms'] == fm['wait_ms']
                   and om['max_updater_io'] == fm['max_updater_io'])
    complete = (not healthy_gaps and original['witness_passed']
                and fixed['witness_passed'] and same_policy)
    return {'case_id': 'HDFS-55', 'variant': 'faithful_updater_io_v1',
            'status': 'source_backed_runtime_candidate' if complete else 'incomplete_or_negative',
            'healthy_gaps': healthy_gaps, 'original': original, 'fixed': fixed,
            'same_policy_across_fault_runs': same_policy,
            'detection_claim': False,
            'manifests_sha256': {name: sha(output / name / 'manifest.json')
                                 for name in ('healthy', 'fault-original', 'fault-fixed')}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.output), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
