#!/usr/bin/env python3
"""Mirror the isolated node2 HTTP stage into both 102-check result rows."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
ROOT = CASE.parents[2]
REMOTE = '/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent/rpc-stage/campaign/progress.json'
SSH = ('ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'ZhenyuLi@node2')
TERMINAL = {'budget_complete', 'queue_exhausted',
            'candidate_target_exception'}


def atomic(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile('w', dir=path.parent,
                                     prefix='.' + path.name + '.',
                                     suffix='.tmp', delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        temporary = Path(handle.name)
    temporary.replace(path)


def read_remote() -> dict | None:
    result = subprocess.run((*SSH, 'cat ' + REMOTE),
                            capture_output=True, text=True)
    if result.returncode:
        return None
    return json.loads(result.stdout)


def publish(rpc: dict) -> None:
    for case_id in ('SOLR-36', 'SOLR-37'):
        stage1 = json.loads(
            (CASE / f'campaign/final-audit-{case_id}.json').read_text())
        stage1_identity = json.loads(
            (CASE / f'campaign/identity-audit-{case_id}.json').read_text())
        result_path = ROOT / case_id / 'result.json'
        result = json.loads(result_path.read_text())
        rpc_n = rpc['fault_trials']
        strict = stage1['strict_injections'] + rpc['strict_injections']
        reached = (stage1_identity[
            'strict_postfault_same_last_fault_child_or_collection_scope']
            + rpc['same_child_post_target_trials'][case_id])
        thrown = (stage1['strict_exact_target_throw_trials']
                  + rpc['exact_target_throw_trials'][case_id])
        status = ('target_exception_candidate_source_review'
                  if rpc['status'] == 'candidate_target_exception'
                  else 'fuzz_running' if rpc['status'] == 'running'
                  else 'campaign_budget_complete_source_audit_pending')
        result.update(
            status=status,
            methodology='coverage_io_independent_asm_jacoco',
            fault_trials=stage1['fault_trials'] + rpc_n,
            strict_injections=strict,
            post_fault_target_reach_trials=reached,
            target_after_fault=reached,
            target_exception_after_fault_trials=thrown,
            total_attempts=stage1['total_attempts'] + rpc['total_attempts'],
            elapsed_seconds=round(result['baseline_seconds']
                                  + stage1['elapsed_seconds']
                                  + rpc['elapsed_seconds'], 3),
            zk_stage_trials=stage1['fault_trials'],
            zk_stage_target_exceptions=stage1['strict_exact_target_throw_trials'],
            rpc_stage_progress=rpc,
            rpc_stage_fault_trials=rpc_n,
            rpc_stage_strict_injections=rpc['strict_injections'],
            rpc_stage_post_fault_target_reach_trials=(
                rpc['same_child_post_target_trials'][case_id]),
            rpc_stage_target_exception_after_fault_trials=(
                rpc['exact_target_throw_trials'][case_id]),
            evidence=('.study-repairs/unit-test-pivot/cases/SOLR-36/'
                      'independent/rpc-stage/campaign/progress.json'),
            updated_at=time.time())
        atomic(result_path, result)
    subprocess.run(('python3', str(ROOT / 'checklist.py'), 'render'),
                   stdout=subprocess.DEVNULL, check=True)


def main() -> None:
    last = None
    while True:
        rpc = read_remote()
        if rpc is None:
            time.sleep(20)
            continue
        key = (rpc['status'], rpc['fault_trials'])
        if key != last:
            atomic(HERE / 'campaign/progress.json', rpc)
            publish(rpc)
            print(f'RPC mirrored {rpc["status"]} {rpc["fault_trials"]}', flush=True)
            last = key
        if rpc['status'] in TERMINAL:
            break
        time.sleep(20)


if __name__ == '__main__':
    main()
