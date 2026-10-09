#!/usr/bin/env python3
"""Mirror completed SOLR-18 raw runs to node2, verify SHA-256, then prune derived files."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path('/users/ZhenyuLi/solr18-actor-v2-runs')
DEST = '/users/ZhenyuLi/solr18-actor-v2-runs'
HOST = 'ZhenyuLi@node2'
KEY = Path('/users/ZhenyuLi/.ssh/id_ed25519_nodes')
RECEIPT = HERE / 'mirror-receipt.json'
SSH = ['ssh', '-i', str(KEY), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=5']
NODE2_LOCAL = socket.gethostname().split('.')[0] == 'node2'


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def mirror_run(run_id: str, prune_derived: bool = False) -> None:
    if not re.fullmatch(r'(?:trial-\d{3}|healthy-v2-[ab]|original-a)', run_id):
        raise ValueError(run_id)
    receipt = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else {
        'schema_version': 1, 'source_node': 'node0', 'destination_node': 'node2',
        'source_root': str(ROOT), 'destination_root': DEST,
        'runs': {}}
    if run_id in receipt['runs']:
        return
    path = ROOT / run_id
    if not (path / 'run.json').exists():
        raise FileNotFoundError(path / 'run.json')
    if NODE2_LOCAL:
        # Node2 is the primary raw store until node0 pulls a verified archive.
        # Keep all raw trace/coverage/JUnit logs locally; prune only derived text.
        if prune_derived and run_id.startswith('trial-'):
            for name in ('covered_probes.txt', 'covered_methods.txt', 'covered_lines.txt'):
                (path / name).unlink(missing_ok=True)
            shutil.rmtree(path / 'scratch', ignore_errors=True)
        files = {p.name: digest(p) for p in sorted(path.iterdir()) if p.is_file()}
        receipt['runs'][run_id] = {
            'verified_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'source_node': 'node2', 'source': str(path),
            'archive_status': 'pending_node0_pull',
            'raw_retained_on_node2': True, 'sha256': files}
        temp = RECEIPT.with_suffix('.json.tmp')
        temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        os.replace(temp, RECEIPT)
        return
    destination = DEST + '/' + run_id
    files = {p.name: digest(p) for p in sorted(path.iterdir()) if p.is_file()}
    transport = 'ssh -i ' + str(KEY) + ' -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5'
    subprocess.run(['rsync', '-a', '--exclude=scratch', '-e', transport,
                    str(path) + '/', HOST + ':' + destination + '/'], check=True)
    check = subprocess.run(['rsync', '-acn', '--exclude=scratch', '-i', '-e', transport,
                            str(path) + '/', HOST + ':' + destination + '/'],
                           capture_output=True, text=True, check=True)
    if check.stdout or check.stderr:
        raise RuntimeError('rsync -acn difference: ' + check.stdout + check.stderr)
    remote = subprocess.run(SSH + [HOST,
                           "find '" + destination + "' -maxdepth 1 -type f -exec sha256sum -- {} +"],
                            capture_output=True, text=True, check=True)
    remote_files = {Path(line[66:]).name: line[:64] for line in remote.stdout.splitlines()}
    if files != remote_files:
        raise RuntimeError('node2 SHA-256 manifest differs for ' + run_id)
    receipt['runs'][run_id] = {
        'verified_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source': str(path), 'destination': HOST + ':' + destination,
        'rsync_checksum_dry_run_exit': 0, 'rsync_checksum_dry_run_output': '',
        'sha256': files}
    temp = RECEIPT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    os.replace(temp, RECEIPT)
    if prune_derived and run_id.startswith('trial-'):
        for name in ('covered_probes.txt', 'covered_methods.txt', 'covered_lines.txt'):
            (path / name).unlink(missing_ok=True)
        shutil.rmtree(path / 'scratch', ignore_errors=True)


if __name__ == '__main__':
    names = sys.argv[1:] or sorted(p.name for p in ROOT.iterdir()
                                    if (p / 'run.json').exists())
    for name in names:
        mirror_run(name, prune_derived=True)
        print('verified ' + name, flush=True)
