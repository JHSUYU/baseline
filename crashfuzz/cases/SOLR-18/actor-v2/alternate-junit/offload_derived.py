#!/usr/bin/env python3
"""Offload only SHA-verified, reproducible closed-trial coverage text."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess

from calibrate import HERE, ROOT, sha

SSH = ['ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=5']
HOST = 'ZhenyuLi@node2'
KINDS = ('covered_lines.txt', 'covered_methods.txt', 'covered_probes.txt')


def atomic(path: Path, value: dict) -> None:
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def free() -> int:
    stat = os.statvfs(ROOT)
    return stat.f_bavail * stat.f_frsize


def run(first: int = 1, last: int = 120) -> dict:
    assert socket.gethostname().split('.')[0] == 'node0'
    state = json.loads((HERE / 'full-state.json').read_text())
    assert state['attempts'] >= last and first == 1 and last == 120
    receipt_path = HERE / f'derived-offload-{first:03d}-{last:03d}.json'
    assert not receipt_path.exists(), receipt_path
    mirror_receipts = [json.loads(path.read_text()) for path in sorted(
        HERE.glob('full-mirror-receipt-*.json'))]
    mirrored = {name for receipt in mirror_receipts
                for name in receipt['closed_trial_ids']}
    files = []
    for number in range(first, last + 1):
        name = f'trial-{number:03d}'
        assert name in mirrored
        row = state['trials'][number - 1]
        assert row['run_id'] == name
        assert row['fault_audit'].get('target_outcome') != 'TARGET_THROW'
        assert row['fault_audit'].get('target_json_equal') is not False
        out = ROOT / name
        manifest = json.loads((out / 'run.json').read_text())
        assert sha(out / 'run.json') == row['run_json_sha256']
        for kind in KINDS:
            path = out / kind
            assert path.is_file()
            expected = manifest['raw_file_sha256'][kind]
            assert sha(path) == expected
            files.append({'path': name + '/' + kind, 'sha256': expected,
                          'allocated_bytes': path.stat().st_blocks * 512})
    assert len(files) == (last - first + 1) * len(KINDS)
    remote_cmd = ('cd ' + shlex.quote(str(ROOT)) + ' && sha256sum '
                  + ' '.join(shlex.quote(item['path']) for item in files))
    remote = subprocess.run([*SSH, HOST, remote_cmd], text=True,
                            check=True, capture_output=True)
    actual = remote.stdout.splitlines()
    expected_lines = [item['sha256'] + '  ' + item['path'] for item in files]
    assert actual == expected_lines, 'remote SHA differs from source/manifest'
    # Verify a full remote-to-local read without creating a competing raw copy.
    smoke = files[len(files) // 2]
    remote_path = str(ROOT / smoke['path'])
    restored = subprocess.run([*SSH, HOST, 'cat ' + shlex.quote(remote_path)],
                              check=True, capture_output=True)
    assert hashlib.sha256(restored.stdout).hexdigest() == smoke['sha256']
    before = free()
    receipt = {'schema_version': 1, 'case_id': 'SOLR-18',
               'phase': 'alternate_original_junit_full',
               'status': 'verified_before_local_offload',
               'source_host': 'node0', 'destination_host': 'node2',
               'source_root': str(ROOT), 'destination_root': str(ROOT),
               'verified_at_utc': datetime.now(timezone.utc).isoformat(),
               'closed_trial_first': first, 'closed_trial_last': last,
               'file_count': len(files), 'files': files,
               'per_file_sha256_manifest_sha256': hashlib.sha256(
                   ('\n'.join(expected_lines) + '\n').encode()).hexdigest(),
               'remote_sha256_check': 'all exact',
               'remote_restore_smoke': smoke,
               'local_free_before_bytes': before,
               'retained_local': ['events.tsv', 'jacoco.exec', 'run.json',
                                  'console.log', 'coverage.log', 'scratch'],
               'scope': 'only closed noncandidate covered_*.txt derived coverage'}
    atomic(receipt_path, receipt)
    for item in files:
        (ROOT / item['path']).unlink()
    receipt['status'] = 'complete'
    receipt['local_free_after_bytes'] = free()
    receipt['deleted_local_file_count'] = len(files)
    receipt['allocated_bytes_before'] = sum(item['allocated_bytes'] for item in files)
    atomic(receipt_path, receipt)
    return receipt


if __name__ == '__main__':
    result = run()
    print(json.dumps({'file_count': result['file_count'],
                      'allocated_bytes_before': result['allocated_bytes_before'],
                      'free_before': result['local_free_before_bytes'],
                      'free_after': result['local_free_after_bytes'],
                      'manifest_sha256': result['per_file_sha256_manifest_sha256']}))
