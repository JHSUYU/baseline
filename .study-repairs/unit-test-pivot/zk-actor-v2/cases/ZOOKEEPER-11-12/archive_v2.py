#!/usr/bin/env python3
"""Archive terminal original-JUnit receipts and raw events for ZK11/12."""

import hashlib
import json
import os
from pathlib import Path
import tarfile

from audit_v2 import audit
from calibrate_v2 import CASE, ROOT, SEEDS
from campaign_v2 import STATE


ARCHIVE = ROOT / 'raw-runs.tar.gz'


def main():
    result = audit(terminal=True)
    temporary = ARCHIVE.with_suffix(ARCHIVE.suffix + '.tmp')
    if temporary.exists():
        raise RuntimeError('previous partial archive present')
    names = [*SEEDS, *(item['run_id'] for item in result['trials'])]
    with tarfile.open(temporary, 'w:gz') as tar:
        tar.add(STATE, arcname='zk1112-v2-state.json', recursive=False)
        tar.add(CASE / 'calibration-receipt.json',
                arcname='calibration-receipt.json', recursive=False)
        for run_id in names:
            for filename in ('run.json', 'events.tsv', 'coverage.tsv',
                             'junit.log', 'trial.json'):
                path = ROOT / run_id / filename
                if path.is_file():
                    tar.add(path, arcname=run_id + '/' + filename, recursive=False)
                elif filename in ('run.json', 'events.tsv', 'coverage.tsv'):
                    raise RuntimeError(run_id + ' lacks ' + filename)
        interrupted = ROOT / 'interrupted'
        if interrupted.is_dir():
            for path in sorted(interrupted.rglob('*')):
                if path.is_file():
                    tar.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    os.replace(temporary, ARCHIVE)
    output = {'archive': str(ARCHIVE), 'bytes': ARCHIVE.stat().st_size,
              'sha256': hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
              'completed_trial_receipts': len(result['trials']),
              'interrupted_selections': result['interrupted'],
              'checkpoint_sha256': result['checkpoint_sha256_at_audit']}
    print(json.dumps(output, sort_keys=True))


if __name__ == '__main__':
    main()
