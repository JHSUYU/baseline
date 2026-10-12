#!/usr/bin/env python3
"""Move completed, noncandidate trial evidence off a busy campaign node.

The summary and final campaign result stay local. Raw trial directories are
removed only after rsync's checksum comparison confirms the remote copy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


def eligible(summary: dict, max_trials: int) -> bool:
    return (summary.get('finished') is True
            and summary.get('status') == 'budget_or_queue_complete'
            and int(summary.get('fault_trials') or 0) >= max_trials
            and int(summary.get('target_exception_candidates') or 0) == 0
            and summary.get('bug_mark') in (None, 'none')
            and not summary.get('archive_path'))


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f'.tmp.{os.getpid()}')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, path)


def archive_case(base: Path, summary: dict, host: str, destination: Path,
                 ssh_key: Path) -> None:
    campaign_dirs = sorted(path for path in base.iterdir()
                           if path.is_dir() and path.name.startswith('campaign'))
    if not campaign_dirs:
        raise RuntimeError(f'{base.name}: completed case has no campaign directory')
    source_result = Path(summary['campaign_result'])
    if not source_result.is_file() or not source_result.is_relative_to(base):
        raise RuntimeError(f'{base.name}: final result is missing or outside its case')
    final_result = base / 'campaign-result.json'
    shutil.copy2(source_result, final_result)

    ssh = ['ssh', '-i', str(ssh_key), '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes']
    remote = f'ZhenyuLi@{host}'
    subprocess.run(ssh + [remote, 'mkdir', '-p', str(destination)], check=True)
    target = remote + ':' + str(destination) + '/'
    rsync = ['rsync', '-a', '-e', ' '.join(ssh), str(base), target]
    subprocess.run(rsync, check=True)
    verify = subprocess.run(['rsync', '-aicn', '-e', ' '.join(ssh),
                             str(base), target], text=True,
                            capture_output=True, check=True)
    if verify.stdout.strip():
        raise RuntimeError(f'{base.name}: remote checksum verification found differences')

    remote_path = str(destination / base.name)
    atomic_json(base / 'archive.json', {
        'case_id': base.name, 'host': host, 'remote_path': remote_path,
        'campaign_dirs': [path.name for path in campaign_dirs],
        'verified_by': 'rsync -aicn checksum dry run returned no differences',
        'archived_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    summary.update(campaign_result=str(final_result), archive_host=host,
                   archive_path=remote_path)
    atomic_json(base / 'case-summary.json', summary)
    for path in campaign_dirs:
        shutil.rmtree(path)
    print(f'archived {base.name} to {host}:{remote_path}', flush=True)


def scan(root: Path, host: str, destination: Path, ssh_key: Path,
         max_trials: int, only_case: str | None) -> int:
    failures = 0
    for path in sorted(root.glob('*/case-summary.json')):
        if only_case and path.parent.name != only_case:
            continue
        try:
            summary = json.loads(path.read_text())
            if eligible(summary, max_trials):
                archive_case(path.parent, summary, host, destination, ssh_key)
        except (OSError, ValueError, KeyError, RuntimeError,
                subprocess.CalledProcessError) as error:
            failures += 1
            print(f'archive failed for {path.parent.name}: {error}', flush=True)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--result-root', type=Path, required=True)
    parser.add_argument('--remote-host', default='node1')
    parser.add_argument('--remote-dir', type=Path,
                        default=Path('/users/ZhenyuLi/static-rerun/archive-node0'))
    parser.add_argument('--ssh-key', type=Path,
                        default=Path('/users/ZhenyuLi/.ssh/id_ed25519_nodes'))
    parser.add_argument('--max-trials', type=int, default=80)
    parser.add_argument('--case-id')
    parser.add_argument('--interval-seconds', type=int, default=0)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', args.remote_host):
        parser.error('remote-host must be a hostname')
    if args.max_trials < 1 or args.interval_seconds < 0:
        parser.error('max-trials must be positive and interval-seconds nonnegative')
    if not args.result_root.is_dir():
        parser.error('result-root must exist')
    while True:
        failures = scan(args.result_root.resolve(), args.remote_host,
                        args.remote_dir, args.ssh_key, args.max_trials,
                        args.case_id)
        if not args.interval_seconds:
            return int(bool(failures))
        time.sleep(args.interval_seconds)


if __name__ == '__main__':
    raise SystemExit(main())
