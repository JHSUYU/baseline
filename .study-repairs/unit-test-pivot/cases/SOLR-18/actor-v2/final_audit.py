#!/usr/bin/env python3
"""Re-audit checkpoint, original JUnit identity, same-client faults, and raw mirror."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

from actor_audit import audit
from build import CLASSES, HERE
from mirror import DEST, HOST, SSH
from run_native import RUN_ROOT

STATE = HERE / 'campaign-state.json'
MIRROR = HERE / 'mirror-receipt.json'
OFFLOAD = HERE / 'console-offload.json'
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
    assert len(state['trials']) == state['attempts']
    assert len({item['run_id'] for item in state['trials']}) == state['attempts']
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
        digests = mirror['runs'][run_id]['sha256']
        assert mirror['runs'][run_id]['rsync_checksum_dry_run_exit'] == 0
        assert mirror['runs'][run_id]['rsync_checksum_dry_run_output'] == ''
        for name, expected in digests.items():
            assert remote[(run_id, name)] == expected, (run_id, name, 'node2')
        for name in RAW_NAMES:
            local = directory / name
            if name == 'console.log' and not local.exists():
                assert run_id in offloaded and offloaded[run_id]['sha256'] == digests[name]
                assert not item['effective'] and offloaded[run_id]['local_events_jacoco_run_retained']
            else:
                assert sha(local) == digests[name], (run_id, name)
        observed = audit(directory / 'events.tsv', item['plan'])
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
        'new_production_probes': len(probes), 'new_production_methods': len(methods),
        'new_production_lines': len(lines),
        'fault_junit_elapsed_seconds': round(elapsed, 3),
        'original_junit_class_sha256': junit_sha,
        'raw_mirror_source': mirror['source_root'],
        'raw_mirror_destination': mirror['destination_root'],
        'raw_mirror_verified_runs': len(state['trials']),
        'raw_mirror_remote_sha_reverified_files': sum(
            len(mirror['runs'][x['run_id']]['sha256']) for x in state['trials']),
        'noncandidate_consoles_offloaded_to_node2': len(offloaded),
        'graphchecker_runtime': False,
    }


if __name__ == '__main__':
    result = audit_all()
    temp = OUTPUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    os.replace(temp, OUTPUT)
    print(json.dumps(result, sort_keys=True))
