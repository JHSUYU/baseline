#!/usr/bin/env python3
"""Mirror dual-check node2 progress into separate SOLR-36/37 checklist rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time


HERE = Path(__file__).resolve().parent
SSH = ('ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'ZhenyuLi@node2')
BASELINE_SECONDS = 102.743 + 105.004 + 104.037


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent,
                                     prefix='.' + path.name + '.',
                                     suffix='.tmp', delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        temporary = Path(handle.name)
    temporary.replace(path)


def mirror_once() -> dict[str, dict]:
    progress: dict[str, dict] = {}
    for case_id in ('SOLR-36', 'SOLR-37'):
        remote = str(HERE / f'campaign/progress-{case_id}.json')
        content = subprocess.check_output((*SSH, 'cat', remote), text=True)
        row = json.loads(content)
        if row['case_id'] != case_id:
            raise RuntimeError('wrong remote case')
        progress[case_id] = row
    if progress['SOLR-36']['fault_trials'] != progress['SOLR-37']['fault_trials']:
        raise RuntimeError('shared sequence progress is inconsistent')
    subprocess.run((*SSH, 'cd ' + str(HERE) + ' && python3 audit_identity.py >/dev/null'),
                   check=True)
    identity: dict[str, dict] = {}
    for case_id in progress:
        remote = str(HERE / f'campaign/identity-audit-{case_id}.json')
        identity[case_id] = json.loads(
            subprocess.check_output((*SSH, 'cat', remote), text=True))
        if identity[case_id]['fault_trials'] != progress[case_id]['fault_trials']:
            raise RuntimeError(f'{case_id} changed while auditing identity')
    for case_id, row in progress.items():
        result_path = HERE.parent.parent / case_id / 'result.json'
        result = json.loads(result_path.read_text())
        previous = result.get('campaign', {}).get('fault_trials', 0)
        if row['fault_trials'] < previous:
            raise RuntimeError(f'{case_id} checkpoint moved backwards')
        if row['status'] == 'candidate_target_exception':
            public_status = 'target_exception_candidate_source_review'
        elif row['status'] == 'budget_complete' and row['budget']['max_trials'] >= 80:
            public_status = 'campaign_budget_complete_audit_pending'
        elif row['status'] == 'queue_exhausted':
            public_status = 'campaign_queue_exhausted_audit_pending'
        elif row['status'] == 'budget_complete':
            public_status = 'campaign_checkpoint'
        else:
            public_status = 'fuzz_running'
        result.update(
            status=public_status,
            methodology='coverage_io_independent_asm_jacoco',
            target_reached=True,
            baseline_seconds=BASELINE_SECONDS,
            fault_trials=row['fault_trials'],
            strict_injections=row['strict_injections'],
            target_after_fault=identity[case_id][
                'strict_postfault_same_last_fault_child_or_collection_scope'],
            post_fault_target_reach_trials=identity[case_id][
                'strict_postfault_same_last_fault_child_or_collection_scope'],
            post_fault_any_child_trials=identity[case_id][
                'strict_postfault_any_child'],
            logical_identity_audit={key: value for key, value in identity[case_id].items()
                                    if key != 'trials'},
            target_exception_after_fault_trials=row['target_exception_after_fault_trials'],
            elapsed_seconds=round(BASELINE_SECONDS + row['elapsed_seconds'], 3),
            coverage_gain=row['production_probe_gain'],
            campaign=row,
            reason=('Unchanged original ShardSplitTest.test embedded-cluster JUnit. '
                    'Two passing healthy ASM records reach both exact guard sites; '
                    'the shared I/O fault sequence has independent postfault '
                    'reach and exact throw oracles for each case. '
                    'Target exception candidates require source review and replay.'),
            evidence=f'.study-repairs/unit-test-pivot/cases/SOLR-36/independent/'
                     f'campaign/progress-{case_id}.json',
            updated_at=time.time())
        atomic(HERE / f'campaign/progress-{case_id}.json', row)
        atomic(result_path, result)
    subprocess.run(('python3', str(HERE.parents[2] / 'checklist.py'), 'render'),
                   stdout=subprocess.DEVNULL, check=True)
    return progress


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--follow', action='store_true')
    parser.add_argument('--interval', type=int, default=15)
    args = parser.parse_args()
    while True:
        try:
            latest = mirror_once()
            print(json.dumps({case_id: {'status': row['status'],
                                        'fault_trials': row['fault_trials']}
                              for case_id, row in latest.items()}), flush=True)
            if (all(row['status'] in ('budget_complete', 'queue_exhausted')
                    and row['budget']['max_trials'] >= 80
                    for row in latest.values()) or
                    any(row['status'] == 'candidate_target_exception'
                        for row in latest.values())):
                break
        except Exception as error:
            print(f'mirror retry: {error}', flush=True)
        if not args.follow:
            break
        time.sleep(args.interval)
