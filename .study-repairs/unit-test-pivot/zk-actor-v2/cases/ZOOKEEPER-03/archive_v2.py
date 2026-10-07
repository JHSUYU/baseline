#!/usr/bin/env python3
"""Archive a terminal ZK03 original-JUnit campaign after raw audit."""

import hashlib
import json
import os
import tarfile

from audit_v2 import audit
from calibrate_healthy import AGENT, ROOT
from campaign import CHECKPOINT, LEDGER

ARCHIVE = ROOT / 'raw-runs.tar.gz'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    verified = audit(terminal=True)
    if ARCHIVE.exists():
        raise RuntimeError('prior raw archive exists; compare its SHA before replacing')
    temporary = ARCHIVE.with_suffix('.tar.gz.tmp')
    if temporary.exists():
        raise RuntimeError('partial raw archive exists')
    run_ids = ['healthy-a', 'healthy-b'] + [x['run_id'] for x in verified['trials']]
    with tarfile.open(temporary, 'w:gz') as output:
        for path in (CHECKPOINT, LEDGER, AGENT.parent / 'build-receipt.json'):
            if not path.is_file():
                raise RuntimeError('missing campaign/build receipt: ' + str(path))
            output.add(path, arcname=path.name, recursive=False)
        for run_id in run_ids:
            for name in ('run.json', 'events.tsv', 'coverage.tsv', 'junit.log'):
                path = ROOT / run_id / name
                if not path.is_file():
                    raise RuntimeError('missing raw JUnit artifact: ' + str(path))
                output.add(path, arcname=run_id + '/' + name, recursive=False)
        for folder in ('failed-seeds', 'feedback-migration-healthy-union'):
            path = ROOT / folder
            if path.is_dir():
                output.add(path, arcname=folder)
    os.replace(temporary, ARCHIVE)
    print(json.dumps({'archive': str(ARCHIVE), 'bytes': ARCHIVE.stat().st_size,
                      'sha256': sha(ARCHIVE), 'checkpoint_sha256': verified['checkpoint_sha256'],
                      'completed_original_junits': len(verified['trials']),
                      'effective': verified['effective']}, sort_keys=True))


if __name__ == '__main__':
    main()
