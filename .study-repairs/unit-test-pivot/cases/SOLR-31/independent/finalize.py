#!/usr/bin/env python3
"""Wait for the bounded original JUnit campaign and audit release-jar coverage."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import time


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
            terminal = progress['status'] in ('budget_complete', 'queue_exhausted')
            if progress['status'] == 'candidate_target_exception' or (
                    terminal and progress['budget']['max_trials'] >= 80):
                break
        time.sleep(30)

    subprocess.run(('ssh', *SSH_OPTIONS, 'ZhenyuLi@node2',
                    'cd ' + REMOTE_DIR + ' && python3 audit_campaign_coverage.py'),
                   check=True)
    for name in ('campaign/production-coverage-audit.json',
                 'campaign/state.json'):
        subprocess.run(('rsync', '-a', '-e', 'ssh ' + ' '.join(SSH_OPTIONS),
                        'ZhenyuLi@node2:' + REMOTE_DIR + '/' + name,
                        str(HERE / name)), check=True)
    audit = json.loads((HERE / 'campaign/production-coverage-audit.json').read_text())
    result = json.loads(RESULT.read_text())
    result.update(
        coverage_audit=audit,
        production_methods_gain=audit['new_production_methods'],
        production_branch_outcomes_gain=audit['new_production_branch_outcomes'],
        status=('target_exception_candidate_source_review'
                if progress['status'] == 'candidate_target_exception' else
                'campaign_budget_complete_source_audit_pending'),
        evidence='.study-repairs/unit-test-pivot/cases/SOLR-31/independent/campaign/production-coverage-audit.json',
        updated_at=time.time())
    atomic(RESULT, result)
    subprocess.run(('python3', str(HERE.parents[2] / 'checklist.py'), 'render'),
                   stdout=subprocess.DEVNULL, check=True)
    (HERE / 'campaign/finalizer.done').write_text(json.dumps({
        'fault_trials': progress['fault_trials'],
        'status': progress['status'],
        'coverage_audit': audit,
    }, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
