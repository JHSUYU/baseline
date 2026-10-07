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
REMOTE_STATE = '/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent/rpc-stage/campaign/state.json'
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


def read_remote() -> tuple[dict, dict, dict] | None:
    results = [subprocess.run((*SSH, 'cat ' + path), capture_output=True,
                              text=True) for path in (REMOTE, REMOTE_STAGE,
                                                     REMOTE_STATE)]
    if any(result.returncode for result in results):
        return None
    rpc, stage = json.loads(results[0].stdout), json.loads(results[1].stdout)
    state = json.loads(results[2].stdout)
    if len(state['completed']) != rpc['fault_trials']:
        return None
    if (stage['status'] in TERMINAL
            and stage['counts']['selected_plans'] != rpc['fault_trials']):
        return None
    gain_by_case = {case_id: sum(
        row['new_production_probes'] for row in state['completed']
        if row['strict_injection']
        and row['postfault_same_child_guards'][case_id] > 0)
        for case_id in ('SOLR-36', 'SOLR-37')}
    return rpc, stage, gain_by_case


def publish(rpc: dict, stage: dict, gain_by_case: dict) -> None:
    seed_audit = json.loads((HERE / 'seed-audit.json').read_text())
    seed_seconds = sum(item['elapsed_seconds']
                       for item in seed_audit['all_healthy_attempts'])
    for case_id in ('SOLR-36', 'SOLR-37'):
        stage1 = json.loads(
            (CASE / f'campaign/final-audit-{case_id}.json').read_text())
        stage1_identity = json.loads(
            (CASE / f'campaign/identity-audit-{case_id}.json').read_text())
        result_path = ROOT / 'cases' / case_id / 'result.json'
        result = json.loads(result_path.read_text())
        rpc_n = rpc['fault_trials']
        strict = rpc['strict_injections']
        reached = rpc['same_child_post_target_trials'][case_id]
        thrown = rpc['exact_target_throw_trials'][case_id]
        reviewed = (rpc.get('reviewed_expected_target_rejection_trials', 0)
                    if case_id == 'SOLR-36' else 0)
        stage_status = stage['status']
        pending_candidate = (rpc['status'] == 'candidate_target_exception'
                             or stage_status == 'candidate')
        status = ('target_exception_candidate_source_review'
                  if pending_candidate
                  else 'pending_actor_aware_zk_v2_http_source_audit'
                  if stage_status == 'complete'
                  else 'pending_actor_aware_zk_v2_http_queue_exhausted'
                  if stage_status == 'queue_exhausted'
                  else 'campaign_interrupted_resume_pending'
                  if stage_status in ('interrupted', 'incomplete_budget_limit')
                  else 'campaign_checkpoint'
                  if rpc['status'] == 'budget_complete' else 'fuzz_running')
        current_elapsed = round(seed_seconds + rpc['elapsed_seconds'], 3)
        historical_elapsed = round(
            result['baseline_seconds']
            + stage1['elapsed_seconds']
            + result['legacy_http_raw_sender_seed']['all_attempt_elapsed_seconds']
            + result['legacy_http_raw_sender_pilot']['elapsed_seconds']
            + result['legacy_http_role_lazylookup_seed']['elapsed_seconds'], 3)
        if pending_candidate:
            reason = ('An unreviewed exact target exception needs separate '
                      'source review and replay.')
        elif case_id == 'SOLR-36' and reviewed:
            reason = (f'{reviewed} exact ACTIVE-child 503 outcomes were '
                      'source-reviewed as protective rejections with original '
                      'JUnit success; HTTP and actor-aware ZooKeeper coverage '
                      'remain under test.')
        else:
            reason = (f'{reached} strict HTTP trials reached the exact '
                      f'{case_id} guard on the injected child after fault '
                      f'effect; {thrown} exact throws observed. HTTP and '
                      'actor-aware ZooKeeper coverage remain under test.')
        result.update(
            status=status,
            methodology='coverage_io_independent_asm_jacoco_http_actor_exact',
            fault_trials=rpc_n,
            strict_injections=strict,
            post_fault_target_reach_trials=reached,
            target_after_fault=reached,
            target_exception_after_fault_trials=thrown,
            total_attempts=rpc['total_attempts'],
            elapsed_seconds=current_elapsed,
            current_method_elapsed_seconds=current_elapsed,
            historical_coarse_elapsed_seconds=historical_elapsed,
            total_including_legacy_elapsed_seconds=round(
                current_elapsed + historical_elapsed, 3),
            coverage_gain=gain_by_case[case_id],
            coverage_gain_scope=('Current-quality HTTP release-JAR production probes '
                                 'from strict trials reaching this case’s exact '
                                 'same-child guard after the fault effect; legacy '
                                 'ZooKeeper actor-unverified probes excluded.'),
            rpc_stage_shared_production_probe_gain=rpc['production_probe_gain'],
            rpc_stage_case_production_probe_gain=gain_by_case[case_id],
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
            rpc_stage_expected_target_rejection_trials=reviewed,
            rpc_stage_unreviewed_target_exception_trials=thrown - reviewed,
            bug_mark='none',
            new_bug=False,
            reason=reason,
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
        rpc, stage, gain_by_case = pair
        key = (rpc['status'], rpc['fault_trials'], stage['status'],
               stage['counts']['selected_plans'])
        if key != last:
            atomic(HERE / 'campaign/progress.json', rpc)
            atomic(HERE / 'campaign/stage-status.json', stage)
            publish(rpc, stage, gain_by_case)
            print(f'RPC mirrored {stage["status"]} selected={rpc["fault_trials"]} '
                  f'effective={rpc["same_child_post_target_trials"]}', flush=True)
            last = key
        if stage['status'] in TERMINAL:
            break
        time.sleep(20)


if __name__ == '__main__':
    main()
