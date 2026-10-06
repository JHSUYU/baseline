#!/usr/bin/env python3
"""Validate all HDFS-32 run manifests and target-site trial oracles."""
import json
import os
from pathlib import Path
import re

from campaign import RUN_ROOT, STATE, events, selected_guard, selector
from run_native import HDFS, CLIENT, COMMON
import zipfile

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'evidence/final-audit.json'
MESSAGE = ('The block pool is still running. First do a refreshNamenodes '
           'to shutdown the block pool service')


def main():
    state = json.loads(STATE.read_text())
    assert state['finished'] and len(state['trials']) == state['budget'] == 80
    assert not state['late_extension_signal']['extend']
    healthy = json.loads((RUN_ROOT / 'healthy-02/run.json').read_text())
    keys = ('test', 'original_source_commit', 'original_test_jar_sha256',
            'original_hdfs_jar_sha256', 'original_common_jar_sha256',
            'overlay_DataNode_sha256', 'overlay_BlockPoolManager_sha256',
            'overlay_Client_sha256', 'classpath_sha256')
    with zipfile.ZipFile(HDFS) as hdfs, zipfile.ZipFile(CLIENT) as client, zipfile.ZipFile(COMMON) as common:
        production = set()
        for jar in (hdfs, client, common):
            production.update(name[:-6] for name in jar.namelist() if name.endswith('.class'))
    results = []
    for item in state['trials']:
        run_id = item['run_id']
        directory = RUN_ROOT / run_id
        manifest = json.loads((directory / 'run.json').read_text())
        assert manifest['plan'] == item['plan']
        assert manifest['junit_exit'] == item['junit_exit']
        assert not manifest['classpath_has_graphchecker_or_skeleton']
        assert all(manifest[key] == healthy[key] for key in keys)
        probe_path = directory / 'covered_probes.txt'
        if probe_path.exists():
            assert manifest['production_probe_filter'] == 'exact_class_membership_in_original_hdfs_client_common_jars'
            probes = probe_path.read_text().splitlines()
            assert len(probes) == manifest['covered_probes']
            assert all(probe.split('#', 1)[0] in production for probe in probes)
        else:
            assert manifest['junit_exit'] == 124
            assert (directory / 'jacoco.exec').stat().st_size == 0
        trace = events(run_id)
        matched = [selector(row) for row in trace if row[1] == 'FAULT_MATCHED']
        applied_events = [row for row in trace if row[1] == 'FAULT_APPLIED']
        applied = [selector(row) for row in applied_events]
        strict = matched == item['plan'] and applied == item['plan']
        guard = selected_guard(trace)
        last_fault = applied_events[-1][0] if applied_events else 0
        retained = bool(strict and guard is not None and guard[0] > last_fault)
        assert matched == item['matched'] and applied == item['applied']
        assert strict == item['strict_ordered_injection']
        assert retained == item['selected_dn2_guard_after_final_fault']
        log = (directory / 'junit.log').read_text(errors='replace')
        assert 'HDFS32_PROBE_WRITE_ERROR' not in log
        assert 'Cannot record HDFS-32 event' not in log
        if retained:
            exact = [row for row in trace if row[1] == 'TARGET_THROW'
                     and row[3][0] == guard[3][0] and row[3][1] == guard[3][1]
                     and row[0] > last_fault]
            assert len(exact) == item['selected_throw_after_fault_count'] == 1
            assert exact[0][3][3:] == ['java.io.IOException', MESSAGE]
            assert item['all_target_throw_count'] == 2
            assert manifest['junit_exit'] == 0
        failure = None
        if manifest['junit_exit'] == 124:
            failure = 'timeout_before_target' if not retained else 'timeout_after_target'
        elif manifest['junit_exit']:
            failure_lines = re.findall(
                r'testDeleteBlockPool\(org\.apache\.hadoop\.hdfs\.server\.datanode\.TestDeleteBlockPool\):[^\n]*',
                log)
            assert failure_lines
            message = failure_lines[-1].split(': ', 1)[1]
            if message.startswith('HDFS-32 independent RPC response fault '):
                failure = 'direct_injected_rpc_ioexception_before_target'
            elif run_id == 'trial-047' and message == 'Must not delete if any block files exist unless force is true':
                failure = 'source_reviewed_non_target_replica_placement_assumption'
            else:
                raise AssertionError((run_id, message))
            assert not retained
        results.append({'run_id': run_id, 'depth': item['fault_count'],
                        'strict': strict, 'target_after_final_fault': retained,
                        'selected_throw_count': item['selected_throw_after_fault_count'],
                        'junit_exit': manifest['junit_exit'], 'elapsed_seconds': manifest['elapsed_seconds'],
                        'failure_class': failure})
    valid = [x for x in results if x['target_after_final_fault']]
    failures = [x for x in results if x['junit_exit']]
    audit = {
        'case_id': 'HDFS-32', 'original_cluster_junit': healthy['test'],
        'source_commit': healthy['original_source_commit'],
        'selected_source': 'DataNode.java:3819 BlockPoolManager.get guard; line 3822 explicit IOException',
        'selected_runtime_identity': 'first deleteBlockPool guard on second distinct DataNode, same DataNode ID and block-pool ID after final fault',
        'healthy_target_guards': 5, 'healthy_expected_target_throws': 2,
        'fault_trials': len(results), 'strict_ordered_trials': sum(x['strict'] for x in results),
        'target_retaining_trials': len(valid), 'target_retaining_new_target_exceptions': 0,
        'target_retaining_junit_nonzero': 0,
        'junit_nonzero': len(failures),
        'failure_classes': {kind: sum(x['failure_class'] == kind for x in failures)
                            for kind in sorted(set(x['failure_class'] for x in failures))},
        'max_depth_attempted': max(x['depth'] for x in results),
        'max_depth_target_retaining': max(x['depth'] for x in valid),
        'late_extension_signal': state['late_extension_signal'],
        'stop_reason': state['stop_reason'],
        'graphchecker_or_skeleton_on_classpath': False,
        'probe_write_errors': 0,
        'invalid_probe_interference_trials_excluded': 11,
        'legacy_graph_trials_excluded': 3,
        'non_target_trial_047_source_review': {
            'failure': 'original test line 83 expects deleteBlockPool(force=false) on dn0 to reject because block files exist',
            'fault': 'Client.getRpcResponse:Thread-N@@6 in DataStreamer while creating /alpha',
            'log_evidence': 'original pipeline 33229+37271; DataStreamer excludes 33229 after fault; retry allocates /alpha only on 37271',
            'source_evidence': 'FsDatasetImpl.java:3336-3360 rejects force=false only if isBPDirEmpty is false; DFSTestUtil.createFile does not wait for replication onto both DNs',
            'interpretation': 'test assumption invalid after injected replica-placement change; selected second-DataNode guard was not reached',
            'run': 'trial-047',
        },
        'trials': results,
    }
    temp = OUTPUT.with_suffix(OUTPUT.suffix + '.tmp')
    temp.write_text(json.dumps(audit, indent=2, sort_keys=True) + '\n')
    os.replace(temp, OUTPUT)
    print(json.dumps({key: audit[key] for key in ('fault_trials', 'strict_ordered_trials',
          'target_retaining_trials', 'junit_nonzero', 'failure_classes', 'probe_write_errors')}, sort_keys=True))


if __name__ == '__main__':
    main()
