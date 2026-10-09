#!/usr/bin/env python3
"""At campaign terminal, audit both exact targets and publish compact evidence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import time


HERE = Path(__file__).resolve().parent
REMOTE_DIR = str(HERE)
SSH_OPTIONS = ('-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes')


def atomic(path: Path, value: object) -> None:
    with tempfile.NamedTemporaryFile('w', dir=path.parent,
                                     prefix='.' + path.name + '.',
                                     suffix='.tmp', delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    while True:
        paths = [HERE / f'campaign/progress-{case_id}.json'
                 for case_id in ('SOLR-36', 'SOLR-37')]
        if all(path.is_file() for path in paths):
            rows = [json.loads(path.read_text()) for path in paths]
            if all(row['status'] in ('budget_complete', 'queue_exhausted',
                                     'candidate_target_exception')
                   for row in rows):
                break
        time.sleep(30)
    subprocess.run(('ssh', *SSH_OPTIONS, 'ZhenyuLi@node2',
                    'cd ' + REMOTE_DIR
                    + ' && python3 audit_identity.py && python3 audit_campaign.py'),
                   check=True)
    reports = {}
    for case_id in ('SOLR-36', 'SOLR-37'):
        name = f'campaign/final-audit-{case_id}.json'
        subprocess.run(('rsync', '-a', '-e', 'ssh ' + ' '.join(SSH_OPTIONS),
                        'ZhenyuLi@node2:' + REMOTE_DIR + '/' + name,
                        str(HERE / name)), check=True)
        report = json.loads((HERE / name).read_text())
        identity_name = f'campaign/identity-audit-{case_id}.json'
        subprocess.run(('rsync', '-a', '-e', 'ssh ' + ' '.join(SSH_OPTIONS),
                        'ZhenyuLi@node2:' + REMOTE_DIR + '/' + identity_name,
                        str(HERE / identity_name)), check=True)
        identity = json.loads((HERE / identity_name).read_text())
        report['logical_identity_audit'] = {
            key: value for key, value in identity.items() if key != 'trials'}
        reports[case_id] = report
        result_path = HERE.parent.parent / case_id / 'result.json'
        result = json.loads(result_path.read_text())
        unreviewed = [number for number in
                      report['strict_exact_target_throw_trial_numbers']
                      if result.get(f'candidate_{number:04d}_review', {}).get(
                          'classification') != 'not_new_bug_protective_retry']
        previous_campaign = result.pop('campaign', None)
        if previous_campaign is not None:
            result['legacy_zk_coarse_campaign'] = previous_campaign
        result.pop('logical_identity_audit', None)
        result.update(
            campaign_final_audit=report,
            legacy_zk_coarse_identity_audit=report['logical_identity_audit'],
            legacy_zk_coarse_quality_status='actor_unverified',
            legacy_zk_coarse_selected_plans=report['fault_trials'],
            legacy_zk_coarse_total_attempts=report['total_attempts'],
            legacy_zk_coarse_strict_point_matches=report['strict_injections'],
            legacy_zk_coarse_same_child_post_target=(
                identity['strict_postfault_same_last_fault_child_or_collection_scope']),
            legacy_zk_coarse_elapsed_seconds=report['elapsed_seconds'],
            fault_trials=0,
            strict_injections=0,
            target_after_fault=0,
            post_fault_target_reach_trials=0,
            post_fault_any_child_trials=0,
            target_exception_after_fault_trials=0,
            total_attempts=0,
            production_methods_gain=0,
            production_branch_outcomes_gain=0,
            io_family_gain=0,
            coverage_gain=0,
            coverage_gain_scope=('Current-quality counters exclude the ZooKeeper phase: '
                                 'its marker/site/path/ordinal selector lacked a stable '
                                 'actor or SolrZkClient reader binding. Full raw counts '
                                 'are retained under legacy_zk_coarse_*.'),
            status=('target_exception_candidate_source_review'
                    if unreviewed else 'pending_http_and_actor_aware_zk_v2'),
            unreviewed_exact_target_throw_trial_numbers=unreviewed,
            evidence=f'crashfuzz/cases/SOLR-36/independent/{name}',
            updated_at=time.time())
        atomic(result_path, result)
    subprocess.run(('python3', str(HERE.parents[2] / 'checklist.py'), 'render'),
                   stdout=subprocess.DEVNULL, check=True)
    (HERE / 'campaign/finalizer.done').write_text(
        json.dumps(reports, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
