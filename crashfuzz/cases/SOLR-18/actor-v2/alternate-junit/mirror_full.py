#!/usr/bin/env python3
"""Mirror a closed SOLR-18 full-trial range from node0 and verify every SHA."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import tempfile

from calibrate import HERE, ROOT, sha

SSH = ['ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=5']
HOST = 'ZhenyuLi@node2'


def run(start: int, end: int) -> dict:
    assert socket.gethostname().split('.')[0] == 'node0'
    state = json.loads((HERE / 'full-state.json').read_text())
    assert 1 <= start <= end <= state['attempts']
    names = [f'trial-{number:03d}' for number in range(start, end + 1)]
    for number, name in enumerate(names, start):
        row = state['trials'][number - 1]
        assert row['run_id'] == name
        assert sha(ROOT / name / 'run.json') == row['run_json_sha256']
    out = HERE / f'full-mirror-receipt-{start:03d}-{end:03d}.json'
    assert not out.exists(), out
    with tempfile.NamedTemporaryFile(mode='w', prefix='solr18-mirror-', delete=False) as handle:
        handle.write(''.join(name + '/\n' for name in names))
        file_list = Path(handle.name)
    try:
        transport = ' '.join(shlex.quote(arg) for arg in SSH)
        common = ['--files-from=' + str(file_list), '-e', transport,
                  str(ROOT) + '/', HOST + ':' + str(ROOT) + '/']
        subprocess.run(['rsync', '-arS', *common], text=True, check=True,
                       capture_output=True)
        verify = subprocess.run(['rsync', '-acrn', *common], text=True,
                                check=True, capture_output=True)
        assert not verify.stdout and not verify.stderr, verify
        paths = sorted(path for name in names for path in (ROOT / name).rglob('*')
                       if path.is_file())
        local = [sha(path) + '  ' + str(path.relative_to(ROOT)) for path in paths]
        remote_cmd = ('cd ' + shlex.quote(str(ROOT)) + ' && find '
                      + ' '.join(shlex.quote(name) for name in names)
                      + ' -type f -print0 | sort -z | xargs -0 sha256sum')
        remote = subprocess.run([*SSH, HOST, remote_cmd], text=True,
                                check=True, capture_output=True)
        assert local == remote.stdout.splitlines(), 'remote per-file SHA mismatch'
        manifest = '\n'.join(local) + '\n'
        receipt = {'schema_version': 1, 'case_id': 'SOLR-18',
                   'phase': 'alternate_original_junit_full',
                   'source_host': 'node0', 'source_root': str(ROOT),
                   'destination_host': 'node2', 'destination_root': str(ROOT),
                   'verified_at_utc': datetime.now(timezone.utc).isoformat(),
                   'closed_trial_ids': names, 'file_count': len(local),
                   'per_file_sha256_manifest_sha256':
                   hashlib.sha256(manifest.encode()).hexdigest(),
                   'verification': 'rsync -acrn exit0 with empty output, then exact per-file SHA-256 list equality on node0 and node2',
                   'rsync_check_exit': 0, 'rsync_check_output': ''}
        temp = out.with_suffix('.json.tmp')
        temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        os.replace(temp, out)
        return receipt
    finally:
        file_list.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('start', type=int)
    parser.add_argument('end', type=int)
    args = parser.parse_args()
    item = run(args.start, args.end)
    print(json.dumps({'trials': len(item['closed_trial_ids']),
                      'files': item['file_count'],
                      'manifest_sha256': item['per_file_sha256_manifest_sha256']}))
