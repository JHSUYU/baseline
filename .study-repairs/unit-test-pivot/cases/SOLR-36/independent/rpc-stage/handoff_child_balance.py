#!/usr/bin/env python3
"""Resume the HTTP campaign at its natural selected-cap scheduler boundary.

Only the run_stages parent is stopped. Its original-JUnit fuzzer child runs to
budget_complete normally. This watcher installs an already reviewed runner
after the child exits, writes an audited migration receipt, then resumes the
parent. Any candidate or failed gate leaves the parent stopped for review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE / 'campaign'
MIGRATION = ROOT / 'migrations' / '0003-child-source-balance'
PREPARED = ROOT / 'prepared-child-balance'
OLD_SHA = '777428d0560f4ce3145dc9cd8c59dc8e57bb192975d57ffee6eb73c2586dda01'
NEW_SHA = '20dc812a90ea436ee8cf29db4aec8a903fdbddb175cc987ed6d19014e617cd83'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_state(pid: int) -> str | None:
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('State:'):
                return line.split()[1]
    except FileNotFoundError:
        return None
    raise RuntimeError(f'process {pid} has no State in /proc')


def process_command(pid: int) -> str | None:
    try:
        return Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode()
    except FileNotFoundError:
        return None


def child_active(pid: int) -> bool:
    state = process_state(pid)
    command = process_command(pid)
    return state not in (None, 'Z', 'X') and bool(command and 'fuzz_rpc.py' in command)


def parent_is_stopped(pid: int) -> bool:
    return process_state(pid) in ('T', 't') and 'run_stages.py' in (
        process_command(pid) or '')


def atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def checkpoint_state(state: dict, child_pid: int, parent_pid: int) -> str:
    """Return wait, migrate, candidate, or failed without mutating anything."""
    if not parent_is_stopped(parent_pid):
        return 'failed_parent_not_stopped'
    if state['status'] == 'candidate_target_exception':
        return 'candidate_requires_review'
    if state['status'] == 'budget_complete':
        if (state['budget'] != {'max_trials': 80, 'max_faults': 8}
                or len(state['completed']) != 80 or state['active'] is not None):
            return 'failed_unexpected_budget_checkpoint'
        return 'wait' if child_active(child_pid) else 'migrate'
    if not child_active(child_pid):
        return 'failed_child_exited_before_budget'
    return 'wait'


def install_and_resume(parent_pid: int) -> dict:
    active = HERE / 'fuzz_rpc.py'
    staged = PREPARED / 'fuzz_rpc.py'
    if (digest(active) != OLD_SHA or digest(staged) != NEW_SHA
            or (MIGRATION / 'migration.json').exists()):
        raise RuntimeError('runner SHA or prior migration receipt differs')
    if not parent_is_stopped(parent_pid):
        raise RuntimeError('parent resumed before migration')
    MIGRATION.mkdir(parents=True, exist_ok=True)
    backup = MIGRATION / 'fuzz_rpc.before_child_balance.py'
    if backup.exists() and digest(backup) != OLD_SHA:
        raise RuntimeError('existing old runner backup differs')
    if not backup.exists():
        shutil.copy2(active, backup)
    temporary = HERE / '.fuzz_rpc.child_balance.tmp'
    temporary.write_bytes(staged.read_bytes())
    temporary.replace(active)
    if digest(active) != NEW_SHA:
        raise RuntimeError('installed runner SHA differs')
    subprocess.run((sys.executable, '-m', 'unittest', '-q',
                    'test_timeout_stage2', 'test_child_balance_migration'),
                   cwd=HERE, check=True)
    subprocess.run((sys.executable, 'migrate_child_balance.py'), cwd=HERE,
                   check=True)
    receipt = json.loads((MIGRATION / 'migration.json').read_text())
    if (receipt['new_runner_sha256'] != NEW_SHA
            or receipt['completed_plans'] != 80
            or digest(ROOT / 'state.json') != receipt['new_state_sha256']):
        raise RuntimeError('migration receipt did not verify')
    os.kill(parent_pid, signal.SIGCONT)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-pid', required=True, type=int)
    parser.add_argument('--child-pid', required=True, type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-wait-seconds', type=int, default=21600)
    arguments = parser.parse_args()
    deadline = time.monotonic() + arguments.max_wait_seconds
    last_completed = None
    while True:
        state = json.loads((ROOT / 'state.json').read_text())
        action = checkpoint_state(state, arguments.child_pid, arguments.parent_pid)
        completed = len(state['completed'])
        if completed != last_completed or action != 'wait':
            print(json.dumps({'completed': completed, 'status': state['status'],
                              'action': action}, sort_keys=True), flush=True)
            last_completed = completed
        if arguments.dry_run:
            return
        if action == 'migrate':
            try:
                receipt = install_and_resume(arguments.parent_pid)
                atomic(MIGRATION / 'watcher-status.json',
                       {'status': 'resumed_parent', 'receipt': receipt})
                print(json.dumps({'status': 'resumed_parent',
                                  'new_runner_sha256': NEW_SHA}), flush=True)
                return
            except Exception as error:
                atomic(MIGRATION / 'watcher-status.json',
                       {'status': 'migration_failed_parent_stopped',
                        'reason': str(error)})
                raise
        if action != 'wait':
            atomic(MIGRATION / 'watcher-status.json',
                   {'status': action, 'completed': completed})
            return
        if time.monotonic() > deadline:
            atomic(MIGRATION / 'watcher-status.json',
                   {'status': 'waiting_timeout', 'completed': completed})
            return
        time.sleep(10)


if __name__ == '__main__':
    main()
