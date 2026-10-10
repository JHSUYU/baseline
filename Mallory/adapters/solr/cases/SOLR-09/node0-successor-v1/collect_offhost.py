#!/usr/bin/env python3
"""Floor-gated, SHA-verified node0 to node2 SOLR-09 terminal collector."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

BASE = Path('/users/ZhenyuLi/baseline')
HERE = Path(__file__).resolve().parent
SOURCE = BASE / 'data/mallory/full_solr09_runtime_role_v1_node0/SOLR-09'
RECEIPT = BASE / 'data/mallory/evidence_archives/SOLR-09-node0-v1-offhost-receipt.json'
REMOTE_SCRIPT = HERE / 'remote_finalize.py'
REMOTE_TEMP = BASE / 'data/mallory/offhost_solr09_runtime_role_v1_node0/.SOLR-09.tmp'
SESSION = 'mallory-solr09-node0-full'
SSH = ['ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'node2']
RSYNC_SSH = 'ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes'
FLOOR = 5 * 1024**3
SAFETY = 64 * 1024**2
TERMINAL = {'budget_exhausted', 'queue_exhausted', 'healthy_seed_invalid',
            'healthy_no_injectable_door', 'healthy_attestation_failed',
            'healthy_node_identity_missing', 'fault_trials_not_attested'}


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


def package_preflight() -> dict:
    if socket.gethostname().split('.')[0] != 'node0':
        raise RuntimeError('collector must run on node0')
    rows = json.loads((HERE / 'sha-manifest.json').read_text())['files']
    for name, expected in rows.items():
        path = HERE / name
        if not path.is_file() or digest(path) != expected['sha256'] or path.stat().st_size != expected['bytes']:
            raise ValueError(f'package SHA mismatch: {name}')
    if shutil.disk_usage(BASE).free < FLOOR + SAFETY:
        raise RuntimeError('node0 5 GiB floor plus safety would be violated')
    remote_sha = subprocess.check_output(SSH + ['sha256sum', str(REMOTE_SCRIPT)], text=True).split()[0]
    if remote_sha != digest(REMOTE_SCRIPT):
        raise ValueError('node2 receiver SHA mismatch')
    remote = json.loads(subprocess.check_output(
        SSH + ['python3', str(REMOTE_SCRIPT), '--capacity', '0'], text=True))
    return {'package_manifest_sha256': digest(HERE / 'sha-manifest.json'),
            'receiver_sha256': remote_sha, 'remote_free': remote['free'],
            'local_free': shutil.disk_usage(BASE).free}


def terminal_manifest() -> dict:
    result_path = SOURCE / 'result.json'
    config_path = SOURCE / 'config.json'
    if not result_path.is_file() or not config_path.is_file():
        raise FileNotFoundError('terminal result or config missing')
    result = json.loads(result_path.read_text())
    if (result.get('case_id') != 'SOLR-09' or result.get('status') not in TERMINAL
            or result.get('calibration_only') is not False
            or json.loads(config_path.read_text()) !=
            json.loads((HERE / 'config-full-node0.json').read_text())):
        raise ValueError('SOLR-09 terminal/config identity failed')
    files = files_under(SOURCE)
    if files.get('result.json', {}).get('sha256') != digest(result_path):
        raise ValueError('result missing from file manifest')
    return {'schema_version': 1, 'case_id': 'SOLR-09', 'status': result['status'],
            'fault_trials_completed': result.get('fault_trials_completed'),
            'source_host': 'node0', 'source_root': str(SOURCE),
            'result_sha256': files['result.json']['sha256'], 'files': files}


def remote(args: list[str], payload: str | None = None) -> dict:
    result = subprocess.run(SSH + ['python3', str(REMOTE_SCRIPT)] + args,
                            input=payload, text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def collect() -> dict:
    package = package_preflight()
    manifest = terminal_manifest()
    size = sum(row['bytes'] for row in manifest['files'].values())
    prepared = remote(['--prepare', str(size)])
    if not prepared.get('already_final'):
        subprocess.run(['rsync', '-a', '--checksum', '--no-links', '-e', RSYNC_SSH,
                        str(SOURCE) + '/', 'node2:' + str(REMOTE_TEMP) + '/'], check=True)
    sealed = remote(['--finalize'], json.dumps(manifest, sort_keys=True))
    if files_under(SOURCE) != manifest['files']:
        raise ValueError('source evidence changed during offhost transfer')
    receipt = {'schema_version': 1, 'case_id': 'SOLR-09', 'status': manifest['status'],
               'fault_trials_completed': manifest['fault_trials_completed'],
            'source_result_sha256': manifest['result_sha256'],
               'staged_config_sha256': digest(HERE / 'config-full-node0.json'),
               'emitted_config_sha256': manifest['files']['config.json']['sha256'],
               'source_files': manifest['files'], 'source_raw_preserved': True,
               'remote_raw_root': sealed['final'],
               'remote_manifest_sha256': sealed['manifest_sha256'],
               'collector_sha256': digest(Path(__file__)),
               'package_manifest_sha256': package['package_manifest_sha256'],
               'receiver_sha256': package['receiver_sha256']}
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    if RECEIPT.exists():
        if json.loads(RECEIPT.read_text()) != receipt:
            raise ValueError('existing collector receipt differs')
    else:
        temporary = RECEIPT.with_name('.' + RECEIPT.name + f'.{os.getpid()}.tmp')
        with temporary.open('x') as output:
            json.dump(receipt, output, sort_keys=True, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        temporary.rename(RECEIPT)
    return {'result_sha256': manifest['result_sha256'],
            'offhost_manifest_sha256': sealed['manifest_sha256'],
            'receipt_sha256': digest(RECEIPT), 'files': len(manifest['files'])}


def watch() -> dict:
    deadline = time.monotonic() + 2 * 3600
    while time.monotonic() < deadline:
        active = subprocess.run(['tmux', 'has-session', '-t', SESSION],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not active and (SOURCE / 'result.json').is_file():
            result = json.loads((SOURCE / 'result.json').read_text())
            if result.get('status') in TERMINAL:
                return collect()
        time.sleep(15)
    raise TimeoutError('SOLR-09 full did not reach a sealed terminal result')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight-only', action='store_true')
    mode.add_argument('--collect-once', action='store_true')
    mode.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    result = (package_preflight() if args.preflight_only else
              collect() if args.collect_once else watch())
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
