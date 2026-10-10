#!/usr/bin/env python3
"""Node2 receiver for the node0 SOLR-09 terminal raw evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys

BASE = Path('/users/ZhenyuLi/baseline')
PARENT = BASE / 'data/mallory/offhost_solr09_runtime_role_v1_node0'
TEMP = PARENT / '.SOLR-09.tmp'
FINAL = PARENT / 'SOLR-09'
FLOOR = 5 * 1024**3
SAFETY = 256 * 1024**2


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def files_under(root: Path) -> dict[str, dict]:
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'symlink in evidence: {path}')
        if path.is_file():
            files[path.relative_to(root).as_posix()] = {
                'sha256': digest(path), 'bytes': path.stat().st_size}
    return files


def check_capacity(size: int) -> int:
    if size < 0:
        raise ValueError('negative size')
    free = shutil.disk_usage(BASE).free
    if free < FLOOR + SAFETY + size:
        raise RuntimeError(f'node2 disk reserve would be violated: free={free} size={size}')
    return free


def finalize(manifest: dict) -> dict:
    if manifest.get('schema_version') != 1 or manifest.get('case_id') != 'SOLR-09':
        raise ValueError('wrong manifest identity')
    if manifest.get('status') not in ('budget_exhausted', 'queue_exhausted',
                                      'healthy_seed_invalid', 'healthy_no_injectable_door',
                                      'healthy_attestation_failed',
                                      'healthy_node_identity_missing',
                                      'fault_trials_not_attested'):
        raise ValueError('campaign is not terminal')
    expected = manifest.get('files')
    if not isinstance(expected, dict) or not expected or 'result.json' not in expected:
        raise ValueError('missing terminal files')
    if manifest.get('result_sha256') != expected['result.json']['sha256']:
        raise ValueError('result SHA mismatch')
    if FINAL.exists():
        archived = json.loads((FINAL / 'offhost-manifest.json').read_text())
        if archived != manifest or files_under(FINAL) != {
                **expected, 'offhost-manifest.json': {
                    'sha256': digest(FINAL / 'offhost-manifest.json'),
                    'bytes': (FINAL / 'offhost-manifest.json').stat().st_size}}:
            raise ValueError('existing offhost archive differs')
        return {'final': str(FINAL), 'manifest_sha256': digest(FINAL / 'offhost-manifest.json')}
    if not TEMP.is_dir() or files_under(TEMP) != expected:
        raise ValueError('offhost copy differs from source SHA manifest')
    payload = json.dumps(manifest, sort_keys=True, indent=2) + '\n'
    record = TEMP / 'offhost-manifest.json'
    with record.open('x') as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    TEMP.rename(FINAL)
    return {'final': str(FINAL), 'manifest_sha256': digest(FINAL / 'offhost-manifest.json')}


def main() -> None:
    if socket.gethostname().split('.')[0] != 'node2':
        raise RuntimeError('offhost receiver must run on node2')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capacity', type=int)
    parser.add_argument('--prepare', type=int)
    parser.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    if sum(value is not None and value is not False for value in
           (args.capacity, args.prepare, args.finalize)) != 1:
        parser.error('select one action')
    if args.capacity is not None:
        print(json.dumps({'free': check_capacity(args.capacity)}, sort_keys=True))
    elif args.prepare is not None:
        if FINAL.exists():
            print(json.dumps({'already_final': True, 'final': str(FINAL)}, sort_keys=True))
            return
        free = check_capacity(args.prepare)
        PARENT.mkdir(parents=True, exist_ok=True)
        TEMP.mkdir(exist_ok=True)
        print(json.dumps({'free': free, 'temporary': str(TEMP)}, sort_keys=True))
    else:
        print(json.dumps(finalize(json.load(sys.stdin)), sort_keys=True))


if __name__ == '__main__':
    main()
