#!/usr/bin/env python3
"""Compress only finalized original JUnit logs; preserve SHA receipts and TSV."""

import gzip
import hashlib
import json
import os
from pathlib import Path

STAGES = (
    (Path('/users/ZhenyuLi/zk02-actor-v2-afterio-runs'), 'afterio-campaign.json'),
    (Path('/users/ZhenyuLi/zk02-actor-v2-after-response-runs'),
     'after-response-campaign.json'),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compress(root, checkpoint):
    state = json.loads((root / checkpoint).read_text())
    done = {item['run_id'] for item in state['results']}
    if done & {item['run_id'] for item in state['inflight']}:
        raise RuntimeError('checkpoint has a completed trial still inflight')
    summary = {'stage_root': str(root), 'compressed_now': 0, 'already_compressed': 0}
    for run_id in sorted(done):
        dest = root / run_id
        source = dest / 'junit.log'
        archive = dest / 'junit.log.gz'
        manifest = dest / 'junit-log-compression.json'
        if manifest.exists():
            if source.exists() or not archive.exists():
                raise RuntimeError(run_id + ': compression manifest/file mismatch')
            info = json.loads(manifest.read_text())
            if digest(gzip.decompress(archive.read_bytes())) != info['raw_sha256']:
                raise RuntimeError(run_id + ': archived JUnit hash mismatch')
            summary['already_compressed'] += 1
            continue
        if not source.exists() or archive.exists():
            raise RuntimeError(run_id + ': source/archive state unexpected')
        raw = source.read_bytes()
        with (dest / 'junit.log.gz.tmp').open('wb') as stream:
            with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as output:
                output.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        zipped = (dest / 'junit.log.gz.tmp').read_bytes()
        if gzip.decompress(zipped) != raw:
            raise RuntimeError(run_id + ': gzip roundtrip failed')
        os.replace(dest / 'junit.log.gz.tmp', archive)
        info = {'run_id': run_id, 'raw_name': 'junit.log',
                'archive_name': 'junit.log.gz', 'raw_bytes': len(raw),
                'raw_sha256': digest(raw), 'archive_bytes': len(zipped),
                'archive_sha256': digest(zipped)}
        temp = dest / 'junit-log-compression.json.tmp'
        temp.write_text(json.dumps(info, indent=2, sort_keys=True) + '\n')
        os.replace(temp, manifest)
        source.unlink()
        summary['compressed_now'] += 1
    return summary


if __name__ == '__main__':
    print(json.dumps([compress(root, checkpoint) for root, checkpoint in STAGES],
                     sort_keys=True))
