#!/usr/bin/env python3
"""Wait for SOLR-38 terminal checkpoint and publish compact source-review evidence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import time

from mirror import mirror_once

HERE = Path(__file__).resolve().parent
RESULT = HERE.parent / 'result.json'
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
    progress_file = HERE / 'campaign/progress.json'
    while True:
        if progress_file.is_file():
            progress = json.loads(progress_file.read_text())
            if progress['status'] == 'candidate_target_exception' or progress['status'] in (
                    'budget_complete', 'queue_exhausted'):
                break
        time.sleep(30)
    progress = mirror_once()
    subprocess.run(('ssh', *SSH_OPTIONS, 'ZhenyuLi@node2',
                    'cd ' + REMOTE_DIR + ' && python3 final_audit.py'), check=True)
    subprocess.run(('rsync', '-a', '-e', 'ssh ' + ' '.join(SSH_OPTIONS),
                    'ZhenyuLi@node2:' + REMOTE_DIR + '/campaign/final-audit.json',
                    str(HERE / 'campaign/final-audit.json')), check=True)
    audit = json.loads((HERE / 'campaign/final-audit.json').read_text())
    result = json.loads(RESULT.read_text())
    result.update(
        final_audit=audit,
        io_family_gain=audit['valid_semantic_io_family_gain'],
        raw_io_family_gain=audit['valid_raw_io_family_gain'],
        production_methods_gain=audit['new_production_methods'],
        production_branch_outcomes_gain=audit['new_production_branch_outcomes'],
        status=('target_exception_candidate_source_review'
                if progress['status'] == 'candidate_target_exception' else
                'campaign_budget_complete_source_audit_pending'
                if progress['status'] == 'budget_complete' else
                'campaign_queue_exhausted_source_audit_pending'),
        evidence='.study-repairs/unit-test-pivot/cases/SOLR-38/independent/campaign/final-audit.json',
        updated_at=time.time())
    atomic(RESULT, result)
    subprocess.run(('python3', str(HERE.parents[2] / 'checklist.py'), 'render'),
                   stdout=subprocess.DEVNULL, check=True)
    (HERE / 'campaign/finalizer.done').write_text(json.dumps({
        'fault_trials': progress['fault_trials'],
        'status': progress['status'],
        'final_audit': audit,
    }, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
