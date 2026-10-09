#!/usr/bin/env python3
"""Re-audit checkpoint, original JUnit identity, same-client faults, and raw mirror."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from actor_audit import audit
from build import CLASSES, HERE
from mirror import DEST, HOST, NODE2_LOCAL, SSH
from run_native import RUN_ROOT

STATE = HERE / 'campaign-state.json'
MIRROR = HERE / 'mirror-receipt.json'
OFFLOAD = HERE / 'console-offload.json'
RAW_OFFLOAD = HERE / 'noncandidate-raw-offload.json'
NODE2_PULL = HERE / 'node2-pull-receipt.json'
DERIVED_PRUNE = HERE / 'derived-prune-receipt.json'
CALIBRATION = HERE / 'calibration.json'
OUTPUT = HERE / 'final-audit.json'
RAW_NAMES = ('events.tsv', 'jacoco.exec', 'console.log', 'run.json')


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def remote_hashes() -> dict[tuple[str, str], str]:
    if NODE2_LOCAL:
        return {(directory.name, path.name): sha(path)
                for directory in RUN_ROOT.iterdir() if directory.is_dir()
                for path in directory.iterdir() if path.is_file()}
    command = "find '" + DEST + "' -mindepth 2 -maxdepth 2 -type f -exec sha256sum -- {} +"
    output = subprocess.run(SSH + [HOST, command], capture_output=True,
                            text=True, check=True).stdout
    result = {}
    for line in output.splitlines():
        path = Path(line[66:])
        result[(path.parent.name, path.name)] = line[:64]
    return result


def audit_all() -> dict:
    state = json.loads(STATE.read_text())
    mirror = json.loads(MIRROR.read_text())
    offloaded = json.loads(OFFLOAD.read_text())['runs'] if OFFLOAD.exists() else {}
    raw_offloaded = json.loads(RAW_OFFLOAD.read_text())['runs'] if RAW_OFFLOAD.exists() else {}
    pulled = json.loads(NODE2_PULL.read_text())['runs'] if NODE2_PULL.exists() else {}
    pruned = json.loads(DERIVED_PRUNE.read_text())['runs'] if DERIVED_PRUNE.exists() else {}
    remote = remote_hashes()
    calibration = json.loads(CALIBRATION.read_text())
    junit_sha = calibration['junit_class_sha256']
    junit_class = CLASSES / 'org/apache/solr/cloud/AliasIntegrationTest.class'
    assert sha(junit_class) == junit_sha
    assert calibration['source_junit_sha_equal']
    assert calibration['original_a']['exit_code'] == 0
    assert calibration['original_a']['junit_class_sha256'] == junit_sha
    for key in ('actor_seed_a', 'actor_seed_b'):
        seed = calibration[key]
        assert seed['junit_exit'] == 0 and seed['junit_summary_present']
        assert seed['test_started_count'] == 1 and seed['assumption_failure_count'] == 0
        assert not seed['classpath_has_graphchecker_or_skeleton_jar']
    if NODE2_LOCAL:
        migration = json.loads((HERE / 'node2-migration-calibration.json').read_text())
        assert migration['original_junit_exit'] == 0
        assert migration['original_junit_summary_present']
        assert migration['test_started_count'] == 1
        assert migration['selected_target_guard']
        assert migration['selected_target_outcome'] == 'TARGET_EQUAL_CHECK'
        assert migration['junit_class_sha256'] == junit_sha
        assert not migration['classpath_has_graphchecker_or_skeleton_jar']
        for name, expected in migration['sha256'].items():
            assert sha(RUN_ROOT / 'node2-migration-clean' / name) == expected
    assert len(state['trials']) == state['attempts']
    assert len({item['run_id'] for item in state['trials']}) == state['attempts']
    by_id = {item['run_id']: item for item in state['trials']}
    for run_id, entry in pruned.items():
        assert run_id in by_id and int(run_id.split('-')[1]) <= 189
        for name, data in entry['files'].items():
            assert name in ('covered_probes.txt', 'covered_methods.txt', 'covered_lines.txt')
            assert mirror['runs'][run_id]['sha256'][name] == data['sha256']
            assert data['size_bytes'] > 0
    executed_plans = {tuple(item['plan']) for item in state['trials']}
    pending_plans = {tuple(item['plan']) for item in state['pending']}
    for skipped in state.get('pruned_plans', []):
        plan = tuple(skipped['plan'])
        assert len(plan) > 1 and ':SUITE@@' in plan[0]
        assert plan not in executed_plans and plan not in pending_plans
        witnesses = skipped['witnesses']
        if skipped['reason'] == 'suite_setup_ended_after_first_fault':
            for kind in ('standalone', 'suffix'):
                witness = by_id[witnesses[kind]]
                assert witness['plan'][0] == plan[0]
                assert (len(witness['plan']) == 1) == (kind == 'standalone')
                assert witness['applied'] == [plan[0]]
                assert witness['test_started_count'] == 0 and not witness['effective']
            assert not any(item['effective'] for item in state['trials']
                           if item['plan'][0] == plan[0])
        else:
            assert skipped['reason'] == 'suite_setup_ended_after_observed_fault_prefix'
            prefix = skipped['prefix']
            assert len(prefix) >= 2 and len(plan) > len(prefix)
            assert tuple(prefix) == plan[:len(prefix)]
            solo = by_id[witnesses['standalone']]
            prior = by_id[witnesses['prefix_trial']]
            assert solo['plan'] == [prefix[-1]] and solo['applied'] == [prefix[-1]]
            assert solo['test_started_count'] == 0 and not solo['effective']
            assert prior['applied'] == prefix == prior['plan'][:len(prefix)]
            assert prior['test_started_count'] == 0
            assert prior['selected_target_sequence'] is None and not prior['effective']
    for proposal in state.get('repair_feedback_receipts', []):
        source = by_id[proposal['source_run_id']]
        index = proposal['removed_index']
        assert not source['effective'] and 0 <= index < len(source['plan'])
        assert source['plan'][index] == proposal['removed_selector']
        assert proposal['plan'] == source['plan'][:index] + source['plan'][index + 1:]
        assert '|||'.join(proposal['plan']) in state['known_plans']
        assert proposal['reason'] in ('applied_fault_in_invalid_plan',
                                      'first_unapplied_fault')
        assert source['applied'] == source['plan'][:len(source['applied'])]
        if proposal['reason'] == 'applied_fault_in_invalid_plan':
            assert index < len(source['applied'])
        else:
            assert index == len(source['applied'])
    valid, strict, wrong, lost, unreviewed, expected_fault_site = [], [], [], [], [], []
    probes, methods, lines = set(), set(), set()
    elapsed = 0.0
    all_junit_nonzero = 0
    for item in state['trials']:
        run_id = item['run_id']
        directory = RUN_ROOT / run_id
        metadata = json.loads((directory / 'run.json').read_text())
        assert metadata['plan'] == item['plan']
        assert metadata['original_junit']
        assert not metadata['classpath_has_graphchecker_or_skeleton_jar']
        assert metadata.get('junit_class_sha256', junit_sha) == junit_sha
        assert metadata['junit_exit'] == item['junit_exit']
        assert metadata['elapsed_seconds'] == item['elapsed_seconds']
        assert run_id in mirror['runs']
        mirror_entry = mirror['runs'][run_id]
        digests = mirror_entry['sha256']
        if mirror_entry.get('archive_status') == 'pending_node0_pull':
            assert mirror_entry['raw_retained_on_node2']
            assert NODE2_LOCAL or run_id in pulled
            if run_id in pulled:
                archived = pulled[run_id]
                assert archived['sha256'] == digests
                assert archived['rsync_checksum_dry_run_exit'] == 0
                assert archived['rsync_checksum_dry_run_output'] == ''
                assert archived['node2_raw_retained']
        else:
            assert mirror_entry['rsync_checksum_dry_run_exit'] == 0
            assert mirror_entry['rsync_checksum_dry_run_output'] == ''
        for name, expected in digests.items():
            if name in pruned.get(run_id, {}).get('files', {}):
                # Only named, SHA-attested derived JaCoCo text may be absent.
                if (run_id, name) in remote:
                    assert remote[(run_id, name)] == expected
            else:
                assert remote[(run_id, name)] == expected, (run_id, name, 'node2')
        for name in RAW_NAMES:
            local = directory / name
            if name == 'console.log' and not local.exists():
                assert run_id in offloaded and offloaded[run_id]['sha256'] == digests[name]
                assert not item['effective']
            elif name in ('events.tsv', 'jacoco.exec') and not local.exists():
                receipt = raw_offloaded[run_id]
                assert not item['effective'] and not item['selected_target_throw']
                assert not item['needs_source_review']
                assert receipt['sha256'][name] == digests[name]
                assert receipt['local_plan_run_and_target_receipts_retained']
            else:
                assert sha(local) == digests[name], (run_id, name)
        event_path = directory / 'events.tsv'
        if event_path.exists():
            observed = audit(event_path, item['plan'])
        else:
            remote_path = DEST + '/' + run_id + '/events.tsv'
            content = subprocess.run(SSH + [HOST, "cat -- '" + remote_path + "'"],
                                     capture_output=True, check=True).stdout
            assert hashlib.sha256(content).hexdigest() == digests['events.tsv']
            with tempfile.TemporaryDirectory(prefix='solr18-audit-') as tempdir:
                restored = Path(tempdir) / 'events.tsv'
                restored.write_bytes(content)
                observed = audit(restored, item['plan'])
        assert observed['strict_ordered_faults'] == item['strict_ordered_injection']
        assert observed['all_faults_on_target_client'] == item['all_faults_on_target_client']
        assert observed['target_after_final_fault'] == item['target_after_final_fault']
        assert observed['effective'] == item['effective']
        if item['strict_ordered_injection']:
            strict.append(run_id)
        if item['effective']:
            valid.append(run_id)
            probes.update(item['new_production_probes_vs_healthy'])
            methods.update(item['new_production_methods_vs_healthy'])
            lines.update(item['new_production_lines_vs_healthy'])
            if item['selected_target_throw'] or item['selected_json_equal'] is not True:
                unreviewed.append({'run_id': run_id, 'reason': 'selected assertion outcome'})
            if item['junit_exit']:
                console = (directory / 'console.log').read_text(errors='replace')
                if ('KeeperException$ConnectionLossException' in console
                    and 'Solr18Probe.aliasIo(Solr18Probe.java:111)' in console
                    and 'AliasIntegrationTest.testProperties(AliasIntegrationTest.java:120)' in console):
                    expected_fault_site.append(run_id)
                else:
                    unreviewed.append({'run_id': run_id, 'reason': 'unclassified JUnit failure'})
        elif item['strict_ordered_injection'] and item['selected_target_sequence'] is None:
            lost.append(run_id)
        elif item['strict_ordered_injection'] and item['selected_target_sequence'] is not None \
                and not item['all_faults_on_target_client']:
            wrong.append(run_id)
        elapsed += item['elapsed_seconds']
        all_junit_nonzero += bool(item['junit_exit'])
    assert len(valid) == state['effective']
    return {
        'case_id': 'SOLR-18', 'audited_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'checkpoint_complete': state['inflight'] is None,
        'campaign_finished': state['finished'], 'stop_reason': state.get('stop_reason'),
        'budget': state['budget'], 'max_faults': state['max_faults'],
        'attempts': state['attempts'], 'strict_ordered_injections': len(strict),
        'effective_fault_trials': len(valid), 'wrong_actor_excluded': wrong,
        'selected_target_lost_excluded': lost,
        'selected_target_throw_runs': [x['run_id'] for x in state['trials'] if x['selected_target_throw']],
        'unreviewed_outcomes': unreviewed,
        'effective_junit_nonzero_expected_direct_fault_site': expected_fault_site,
        'all_junit_nonzero_trials': all_junit_nonzero,
        'max_depth_attempted': max((x['fault_count'] for x in state['trials']), default=0),
        'unreachable_suite_suffix_plans_pruned': len(state.get('pruned_plans', [])),
        'unreachable_observed_prefix_suffix_plans_pruned': sum(
            x['reason'] == 'suite_setup_ended_after_observed_fault_prefix'
            for x in state.get('pruned_plans', [])),
        'ordered_deletion_feedback_plans': len(state.get('repair_feedback_receipts', [])),
        'new_production_probes': len(probes), 'new_production_methods': len(methods),
        'new_production_lines': len(lines),
        'fault_junit_elapsed_seconds': round(elapsed, 3),
        'original_junit_class_sha256': junit_sha,
        'raw_mirror_source': mirror['source_root'],
        'raw_mirror_destination': mirror['destination_root'],
        'raw_mirror_verified_runs': sum(
            mirror['runs'][x['run_id']].get('archive_status') != 'pending_node0_pull'
            or x['run_id'] in pulled
            for x in state['trials']),
        'raw_archive_pending_node0_pull_runs': [x['run_id'] for x in state['trials']
            if mirror['runs'][x['run_id']].get('archive_status') == 'pending_node0_pull'
            and x['run_id'] not in pulled],
        'node0_archive_verified_runs': sum(x['run_id'] in pulled for x in state['trials']),
        'node0_archive_sha_attested_files': sum(
            len(pulled[x['run_id']]['sha256']) for x in state['trials']
            if x['run_id'] in pulled),
        'derived_coverage_files_pruned_after_sha': sum(
            (run_id, name) not in remote for run_id, entry in pruned.items()
            for name in entry['files']),
        'derived_coverage_bytes_reclaimed': sum(
            data['size_bytes'] for run_id, entry in pruned.items()
            for name, data in entry['files'].items()
            if (run_id, name) not in remote),
        'derived_prune_receipt_sha256': sha(DERIVED_PRUNE) if DERIVED_PRUNE.exists() else None,
        'raw_mirror_remote_sha_reverified_files': sum(
            (x['run_id'], name) in remote
            for x in state['trials']
            for name in mirror['runs'][x['run_id']]['sha256']
            if not NODE2_LOCAL or
            mirror['runs'][x['run_id']].get('archive_status') != 'pending_node0_pull'),
        'raw_primary_sha_reverified_files': sum(
            (x['run_id'], name) in remote
            for x in state['trials']
            for name in mirror['runs'][x['run_id']]['sha256']),
        'noncandidate_consoles_offloaded_to_node2': len(offloaded),
        'noncandidate_event_jacoco_pairs_offloaded_to_node2': len(raw_offloaded),
        'graphchecker_runtime': False,
    }


if __name__ == '__main__':
    result = audit_all()
    temp = OUTPUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    os.replace(temp, OUTPUT)
    print(json.dumps(result, sort_keys=True))
