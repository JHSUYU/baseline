#!/usr/bin/env python3
"""Pull completed node2 trials to node0 and verify both copies without keys on node2."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from mirror import DEST, HOST, KEY, ROOT, SSH, digest

HERE = Path(__file__).resolve().parent
RECEIPT = HERE / 'node2-pull-receipt.json'
REMOTE_CASE = '/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-18/actor-v2'
MIN_NODE0_FREE_BYTES = int(2.6 * (1 << 30))
TRANSPORT = 'ssh -i ' + str(KEY) + ' -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5'


def remote_json(name: str) -> dict:
    path = REMOTE_CASE + '/' + name
    output = subprocess.check_output(SSH + [HOST, "cat -- '" + path + "'"], text=True)
    return json.loads(output)


def save(doc: dict) -> None:
    temp = RECEIPT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n')
    os.replace(temp, RECEIPT)


def pull(run_id: str, expected: dict[str, str], doc: dict) -> None:
    if not re.fullmatch(r'trial-\d{3,}', run_id):
        raise ValueError(run_id)
    if shutil.disk_usage('/').free < MIN_NODE0_FREE_BYTES:
        raise RuntimeError('node0 below 2.6 GiB pull guard')
    source = DEST + '/' + run_id
    directory = ROOT / run_id
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(['rsync', '-a', '--exclude=scratch', '-e', TRANSPORT,
                    HOST + ':' + source + '/', str(directory) + '/'], check=True)
    check = subprocess.run(['rsync', '-acn', '--exclude=scratch', '-i', '-e', TRANSPORT,
                            HOST + ':' + source + '/', str(directory) + '/'],
                           capture_output=True, text=True, check=True)
    if check.stdout or check.stderr:
        raise RuntimeError('rsync checksum difference: ' + check.stdout + check.stderr)
    local = {path.name: digest(path) for path in directory.iterdir() if path.is_file()}
    if local != expected:
        raise RuntimeError('node0 raw SHA manifest differs: ' + run_id)
    remote = subprocess.check_output(SSH + [HOST,
        "find '" + source + "' -maxdepth 1 -type f -exec sha256sum -- {} +"], text=True)
    remote_hashes = {Path(line[66:]).name: line[:64] for line in remote.splitlines()}
    if remote_hashes != expected:
        raise RuntimeError('node2 raw SHA manifest differs: ' + run_id)
    doc['runs'][run_id] = {
        'verified_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source': HOST + ':' + source, 'destination': str(directory),
        'rsync_checksum_dry_run_exit': 0, 'rsync_checksum_dry_run_output': '',
        'sha256': expected, 'node2_raw_retained': True}
    save(doc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-runs', type=int, default=20)
    args = parser.parse_args()
    state = remote_json('campaign-state.json')
    mirror = remote_json('mirror-receipt.json')
    doc = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else {
        'schema_version': 1, 'source_node': 'node2', 'destination_node': 'node0',
        'source_root': DEST, 'destination_root': str(ROOT), 'runs': {}}
    available = [item['run_id'] for item in state['trials']
                 if item['run_id'] in mirror['runs']
                 and mirror['runs'][item['run_id']].get('archive_status') == 'pending_node0_pull'
                 and item['run_id'] not in doc['runs']]
    count = 0
    for run_id in available[:args.max_runs]:
        pull(run_id, mirror['runs'][run_id]['sha256'], doc)
        count += 1
    subprocess.run(['rsync', '-a', '-e', TRANSPORT, str(RECEIPT),
                    HOST + ':' + REMOTE_CASE + '/' + RECEIPT.name], check=True)
    check = subprocess.run(['rsync', '-acn', '-i', '-e', TRANSPORT, str(RECEIPT),
                            HOST + ':' + REMOTE_CASE + '/' + RECEIPT.name],
                           capture_output=True, text=True, check=True)
    if check.stdout or check.stderr:
        raise RuntimeError('node2 receipt checksum difference')
    print(json.dumps({'pulled': count, 'total_verified': len(doc['runs']),
                      'available': len(available)}, sort_keys=True))


if __name__ == '__main__':
    main()
