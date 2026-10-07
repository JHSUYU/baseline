#!/usr/bin/env python3
"""Stop the V2 worker only after a durable trial checkpoint is written."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import campaign_v2 as v2


def state() -> dict:
    return json.loads(v2.STATE.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active_members(pgid: int) -> list[int]:
    output = subprocess.check_output(['ps', '-eo', 'pid=,pgid=,stat='], text=True)
    members = []
    for line in output.splitlines():
        pid, group, status = line.split(None, 2)
        if int(group) == pgid and not status.startswith('Z'):
            members.append(int(pid))
    return members


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--pgid', type=int, required=True)
    parser.add_argument('--selected', type=int, required=True)
    parser.add_argument('--wait-seconds', type=int, default=420)
    args = parser.parse_args()

    initial = state()
    if (initial['selected_count'] != args.selected or
            len(initial['trials']) != args.selected or
            len(initial['seen']) != args.selected or initial.get('stopped')):
        raise RuntimeError('V2 checkpoint changed before handoff')
    if os.getpgid(args.pid) != args.pgid:
        raise RuntimeError('V2 worker process group changed')
    command = Path(f'/proc/{args.pid}/cmdline').read_bytes().replace(b'\0', b' ')
    if b'campaign_v2.py' not in command:
        raise RuntimeError('expected V2 worker PID is no longer running')

    deadline = time.monotonic() + args.wait_seconds
    while time.monotonic() < deadline:
        current = state()
        if current['selected_count'] > args.selected:
            break
        if not Path(f'/proc/{args.pid}').exists():
            raise RuntimeError('V2 worker exited before the next checkpoint')
        time.sleep(0.1)
    else:
        raise TimeoutError('no complete V2 checkpoint within wait limit')

    os.killpg(args.pgid, signal.SIGTERM)
    for _ in range(100):
        if not active_members(args.pgid):
            break
        time.sleep(0.1)
    members = active_members(args.pgid)
    if members:
        raise RuntimeError(f'V2 process group still has live members: {members}')

    final = state()
    number = final['selected_count']
    if (number < args.selected + 1 or len(final['trials']) != number or
            len(final['seen']) != number):
        raise RuntimeError('handoff did not retain a complete checkpoint')
    pending = v2.ROOT / f'trial-{number + 1:03d}'
    archived = None
    if pending.exists():
        if (pending / 'trial.json').exists():
            raise RuntimeError('next trial has a result outside the checkpoint')
        archived = v2.ROOT / f'interrupted-v2-trial-{number + 1:03d}'
        if archived.exists():
            raise RuntimeError('interrupted trial archive already exists')
        pending.rename(archived)

    receipt = {
        'old_worker_pid': args.pid,
        'old_worker_pgid': args.pgid,
        'selected_before': args.selected,
        'selected_after': number,
        'effective_after': sum(row['effective'] for row in final['trials']),
        'checkpoint_sha256': digest(v2.STATE),
        'policy_sha256': digest(v2.HERE / 'campaign_v3.py'),
        'handoff_script_sha256': digest(Path(__file__)),
        'interrupted_directory': str(archived) if archived else None,
        'stopped': bool(final.get('stopped')),
    }
    v2.atomic(v2.ROOT / 'handoff-v3-receipt.json', receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
