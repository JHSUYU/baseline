#!/usr/bin/env python3
"""Archive terminal trial evidence without regenerable embedded-cluster scratch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE / 'campaign'
ARCHIVE = CAMPAIGN / 'raw-trials-v2.tar.zst'
MANIFEST = CAMPAIGN / 'raw-trials-v2-manifest.json'
RECEIPT = CAMPAIGN / 'raw-trials-v2-receipt.json'


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def verify() -> None:
    expected = json.loads(MANIFEST.read_text())
    found = {}
    decoder = subprocess.Popen(['zstd', '-dc', str(ARCHIVE)], stdout=subprocess.PIPE)
    assert decoder.stdout is not None
    try:
        with tarfile.open(fileobj=decoder.stdout, mode='r|') as archive:
            for member in archive:
                if not member.isfile():
                    raise RuntimeError(f'non-file archive member: {member.name}')
                if member.name not in expected or member.name in found:
                    raise RuntimeError(f'unexpected/duplicate archive member: {member.name}')
                source = archive.extractfile(member)
                assert source is not None
                checksum = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    checksum.update(chunk)
                found[member.name] = {'size': member.size, 'sha256': checksum.hexdigest()}
                if found[member.name] != expected[member.name]:
                    raise RuntimeError(f'archive member mismatch: {member.name}')
    finally:
        decoder.stdout.close()
    if decoder.wait() != 0 or found != expected:
        raise RuntimeError('archive stream or member set mismatch')
    receipt = {'archive_sha256': digest(ARCHIVE),
               'manifest_sha256': digest(MANIFEST),
               'file_count': len(found),
               'uncompressed_bytes': sum(row['size'] for row in found.values()),
               'archive_bytes': ARCHIVE.stat().st_size}
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


def build() -> None:
    state = json.loads((CAMPAIGN / 'state.json').read_text())
    if state['status'] != 'budget_complete' or len(state['completed']) != 128:
        raise RuntimeError('archive only the completed 128-effective checkpoint')
    files = sorted(path for path in (CAMPAIGN / 'trials').rglob('*')
                   if path.is_file() and 'scratch' not in path.relative_to(CAMPAIGN / 'trials').parts)
    manifest = {str(path.relative_to(HERE)): {'size': path.stat().st_size, 'sha256': digest(path)}
                for path in files}
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    paths = CAMPAIGN / 'raw-trials-v2-paths.bin'
    paths.write_bytes(b''.join(name.encode() + b'\0' for name in manifest))
    subprocess.run(['tar', '-C', str(HERE), '--null', '--no-recursion',
                    '-I', 'zstd -1', '-cf', str(ARCHIVE), '-T', str(paths)], check=True)
    verify()


if __name__ == '__main__':
    if sys.argv[1:] == ['--verify-only']:
        verify()
    elif len(sys.argv) == 1:
        build()
    else:
        raise SystemExit('usage: archive_raw_v2.py [--verify-only]')
