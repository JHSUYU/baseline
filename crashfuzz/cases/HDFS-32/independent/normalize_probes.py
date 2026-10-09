#!/usr/bin/env python3
"""Normalize checkpointed probe coverage to production JAR classes, in place."""
import json
import os
from pathlib import Path
import shutil

from run_native import RUN_ROOT, filter_production_probes

HERE = Path(__file__).resolve().parent
STATE = HERE / 'evidence/campaign-state.json'
LEDGER = HERE / 'trial-ledger.jsonl'
BACKUP = HERE / 'evidence/probe-filter-correction'


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def main():
    from campaign import update_result

    state = json.loads(STATE.read_text())
    assert not state['inflight_jobs'], 'Stop campaign and drain active JUnits first'
    BACKUP.mkdir(parents=True, exist_ok=True)
    if not (BACKUP / 'campaign-state.before.json').exists():
        shutil.copy2(STATE, BACKUP / 'campaign-state.before.json')
        shutil.copy2(LEDGER, BACKUP / 'trial-ledger.before.jsonl')
    run_ids = ['healthy-02'] + [item['run_id'] for item in state['trials']]
    counts = {}
    for run_id in run_ids:
        directory = RUN_ROOT / run_id
        path = directory / 'covered_probes.txt'
        before = len(path.read_text().splitlines())
        after = filter_production_probes(path)
        manifest_path = directory / 'run.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['covered_probes'] = after
        manifest['production_probe_filter'] = 'exact_class_membership_in_original_hdfs_client_common_jars'
        atomic_json(manifest_path, manifest)
        counts[run_id] = {'before': before, 'production': after, 'excluded_test_helper_probes': before - after}
    healthy = set((RUN_ROOT / 'healthy-02/covered_probes.txt').read_text().splitlines())
    for item in state['trials']:
        covered = set((RUN_ROOT / item['run_id'] / 'covered_probes.txt').read_text().splitlines())
        item['new_production_probes_vs_healthy'] = sorted(covered - healthy)
    atomic_json(STATE, state)
    temp = LEDGER.with_suffix(LEDGER.suffix + '.tmp')
    temp.write_text(''.join(json.dumps(item, sort_keys=True) + '\n' for item in state['trials']))
    os.replace(temp, LEDGER)
    atomic_json(BACKUP / 'correction.json', {'cause': 'JaCoCo class-prefix filter included test-JAR helper classes such as MiniDFSCluster',
                                            'fix': 'exact membership in original production hdfs, hdfs-client, or common JARs',
                                            'junit_trials_rerun': 0, 'counts': counts})
    update_result(state)
    print(json.dumps({'runs_corrected': len(run_ids), 'completed_trials': len(state['trials']),
                      'excluded_test_helper_probes': sum(x['excluded_test_helper_probes'] for x in counts.values())}))


if __name__ == '__main__':
    main()
