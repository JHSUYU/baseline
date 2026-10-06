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
                    + ' && python3 audit_campaign.py && python3 audit_identity.py'),
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
        result.update(
            campaign_final_audit=report,
            logical_identity_audit=report['logical_identity_audit'],
            target_after_fault=(
                identity['strict_postfault_same_last_fault_child_or_collection_scope']),
            post_fault_target_reach_trials=(
                identity['strict_postfault_same_last_fault_child_or_collection_scope']),
            post_fault_any_child_trials=identity['strict_postfault_any_child'],
            production_methods_gain=report['new_production_methods'],
            production_branch_outcomes_gain=report['new_production_branch_outcomes'],
            io_family_gain=report['new_semantic_io_families'],
            status=('target_exception_candidate_source_review'
                    if report['strict_exact_target_throw_trials'] else
                    'campaign_budget_complete_source_audit_pending'),
            evidence=f'.study-repairs/unit-test-pivot/cases/SOLR-36/independent/{name}',
            updated_at=time.time())
        atomic(result_path, result)
    subprocess.run(('python3', str(HERE.parents[2] / 'checklist.py'), 'render'),
                   stdout=subprocess.DEVNULL, check=True)
    (HERE / 'campaign/finalizer.done').write_text(
        json.dumps(reports, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
