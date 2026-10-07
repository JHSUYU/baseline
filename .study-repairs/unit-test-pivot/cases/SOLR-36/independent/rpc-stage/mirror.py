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
REMOTE_STAGE = '/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent/rpc-stage/campaign/stage-status.json'
SSH = ('ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'ZhenyuLi@node2')
TERMINAL = {'complete', 'queue_exhausted', 'candidate',
            'incomplete_budget_limit', 'interrupted'}


def atomic(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile('w', dir=path.parent,
                                     prefix='.' + path.name + '.',
                                     suffix='.tmp', delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        temporary = Path(handle.name)
    temporary.replace(path)


def read_remote() -> tuple[dict, dict] | None:
    results = [subprocess.run((*SSH, 'cat ' + path), capture_output=True,
                              text=True) for path in (REMOTE, REMOTE_STAGE)]
    if any(result.returncode for result in results):
        return None
    rpc, stage = json.loads(results[0].stdout), json.loads(results[1].stdout)
    if (stage['status'] in TERMINAL
            and stage['counts']['selected_plans'] != rpc['fault_trials']):
        return None
    return rpc, stage


def publish(rpc: dict, stage: dict) -> None:
    for case_id in ('SOLR-36', 'SOLR-37'):
        stage1 = json.loads(
            (CASE / f'campaign/final-audit-{case_id}.json').read_text())
        stage1_identity = json.loads(
            (CASE / f'campaign/identity-audit-{case_id}.json').read_text())
        result_path = ROOT / case_id / 'result.json'
        result = json.loads(result_path.read_text())
        rpc_n = rpc['fault_trials']
        strict = rpc['strict_injections']
        reached = rpc['same_child_post_target_trials'][case_id]
        thrown = rpc['exact_target_throw_trials'][case_id]
        stage_status = stage['status']
        status = ('target_exception_candidate_source_review'
                  if rpc['status'] == 'candidate_target_exception'
                  or stage_status == 'candidate'
                  else 'pending_actor_aware_zk_v2_http_source_audit'
                  if stage_status == 'complete'
                  else 'pending_actor_aware_zk_v2_http_queue_exhausted'
                  if stage_status == 'queue_exhausted'
                  else 'campaign_interrupted_resume_pending'
                  if stage_status in ('interrupted', 'incomplete_budget_limit')
                  else 'campaign_checkpoint'
                  if rpc['status'] == 'budget_complete' else 'fuzz_running')
        result.update(
            status=status,
            methodology='coverage_io_independent_asm_jacoco_http_actor_exact',
            fault_trials=rpc_n,
            strict_injections=strict,
            post_fault_target_reach_trials=reached,
            target_after_fault=reached,
            target_exception_after_fault_trials=thrown,
            total_attempts=rpc['total_attempts'],
            elapsed_seconds=round(result['baseline_seconds']
                                  + stage1['elapsed_seconds']
                                  + rpc['elapsed_seconds'], 3),
            coverage_gain=rpc['production_probe_gain'],
            coverage_gain_scope=('Current-quality HTTP release-JAR production probes; '
                                 'legacy ZooKeeper actor-unverified probes excluded.'),
            legacy_zk_coarse_selected_plans=stage1['fault_trials'],
            legacy_zk_coarse_strict_point_matches=stage1['strict_injections'],
            legacy_zk_coarse_same_child_post_target=stage1_identity[
                'strict_postfault_same_last_fault_child_or_collection_scope'],
            legacy_zk_coarse_target_exceptions=stage1[
                'strict_exact_target_throw_trials'],
            rpc_stage_progress=rpc,
            rpc_stage_control=stage,
            rpc_stage_fault_trials=rpc_n,
            rpc_stage_selected_plans=rpc_n,
            rpc_stage_attempted_junits=rpc['total_attempts'],
            rpc_stage_effective_by_case=rpc['same_child_post_target_trials'],
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
        pair = read_remote()
        if pair is None:
            time.sleep(20)
            continue
        rpc, stage = pair
        key = (rpc['status'], rpc['fault_trials'], stage['status'],
               stage['counts']['selected_plans'])
        if key != last:
            atomic(HERE / 'campaign/progress.json', rpc)
            atomic(HERE / 'campaign/stage-status.json', stage)
            publish(rpc, stage)
            print(f'RPC mirrored {stage["status"]} selected={rpc["fault_trials"]} '
                  f'effective={rpc["same_child_post_target_trials"]}', flush=True)
            last = key
        if stage['status'] in TERMINAL:
            break
        time.sleep(20)


if __name__ == '__main__':
    main()
