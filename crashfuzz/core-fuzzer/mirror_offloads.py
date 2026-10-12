#!/usr/bin/env python3
"""Mirror finished cross-host cases before releasing their destination locks."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'data/crashfuzz/static102-offloads.json'
STAGING = ROOT / '.study-repairs/static102-rerun/offload-staging'
REMOTE_ROOT = Path('/users/ZhenyuLi/static-rerun/results')
SSH = ['ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes']
RSYNC_SHELL = 'ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes'


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f'.tmp.{os.getpid()}')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, path)


def remote_summary(host: str, cid: str) -> dict | None:
    path = REMOTE_ROOT / cid / 'case-summary.json'
    if host == 'node0':
        return json.loads(path.read_text()) if path.is_file() else None
    script = ("import json,pathlib\n"
              f"p=pathlib.Path({str(path)!r})\n"
              "print(json.dumps(json.loads(p.read_text()) if p.is_file() else None))\n")
    result = subprocess.run(SSH + [f'ZhenyuLi@{host}', 'python3', '-'],
                            input=script, text=True, capture_output=True,
                            timeout=20, check=True)
    return json.loads(result.stdout)


def mirror_case(cid: str, source: str, destination: str) -> None:
    if source == 'node0':
        staging = REMOTE_ROOT / cid
        if not staging.is_dir():
            raise FileNotFoundError(f'{cid}: local offload result is missing')
    else:
        staging = STAGING / cid
        staging.mkdir(parents=True, exist_ok=True)
        source_dir = f'ZhenyuLi@{source}:{REMOTE_ROOT / cid}/'
        subprocess.run(
            ['rsync', '-a', '--exclude=.run-case.lock', '-e', RSYNC_SHELL,
             '--delete', source_dir, str(staging) + '/'],
            check=True, timeout=600)
    destination_dir = f'ZhenyuLi@{destination}:{REMOTE_ROOT / cid}/'
    common = ['rsync', '-a', '--exclude=.run-case.lock', '-e', RSYNC_SHELL]
    subprocess.run(common + [str(staging) + '/', destination_dir],
                   check=True, timeout=600)
    verification = subprocess.run(
        ['rsync', '-rcni', '--exclude=.run-case.lock', '-e', RSYNC_SHELL,
         str(staging) + '/', destination_dir],
        check=True, capture_output=True, text=True, timeout=600)
    if verification.stdout.strip():
        raise RuntimeError(f'{cid}: mirror checksum differs: '
                           f'{verification.stdout[:500]}')
    summary = remote_summary(destination, cid)
    if not summary or not summary.get('finished'):
        raise RuntimeError(f'{cid}: mirrored summary is incomplete')


def scan() -> bool:
    manifest = json.loads(MANIFEST.read_text())
    active = False
    for cid, assignment in manifest['cases'].items():
        if not re.fullmatch(r'[A-Z0-9-]+', cid):
            raise ValueError(f'invalid case ID: {cid}')
        if assignment['state'] != 'active':
            continue
        active = True
        source = assignment['execution_host']
        destination = assignment['mirror_host']
        if source not in ('node0', 'node2') or destination != 'node1':
            raise ValueError(f'unexpected offload route: {cid}')
        summary = remote_summary(source, cid)
        if not summary or not summary.get('finished'):
            continue
        mirror_case(cid, source, destination)
        lock_session = assignment['mirror_lock_session']
        lock_status = subprocess.run(
            SSH + [f'ZhenyuLi@{destination}', 'tmux', 'has-session',
                   '-t', lock_session], capture_output=True, timeout=20)
        if lock_status.returncode == 0:
            subprocess.run(SSH + [f'ZhenyuLi@{destination}', 'tmux',
                                  'kill-session', '-t', lock_session],
                           check=True, timeout=20)
        elif lock_status.returncode != 1:
            raise RuntimeError(f'{cid}: cannot verify destination lock session')
        assignment['state'] = 'mirrored'
        assignment['mirrored_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                                   time.gmtime())
        atomic_json(MANIFEST, manifest)
        print(json.dumps({'case_id': cid, 'state': 'mirrored'}), flush=True)
    return not active


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        try:
            complete = scan()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print(f'offload mirror: {error}', flush=True)
            complete = False
        if complete or not args.watch:
            return 0 if complete else 1
        time.sleep(30)


if __name__ == '__main__':
    raise SystemExit(main())
