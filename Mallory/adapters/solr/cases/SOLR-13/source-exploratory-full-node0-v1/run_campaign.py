#!/usr/bin/env python3
"""GO-gated, single-owner SOLR-13 exploratory full campaign on node0."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import preflight


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / 'Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f'
OUT = ROOT / 'data/mallory/campaigns/SOLR-13-source-exploratory-full-node0-v1'
GO = HERE / 'admission-full-node0.json'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('full',), required=True)
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--admission-receipt', type=Path)
    args = parser.parse_args()
    metadata = preflight.main()
    if args.preflight_only:
        print(json.dumps(metadata, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error('dispatch full GO receipt required before starting a JVM')
    if args.admission_receipt.resolve() != GO:
        raise ValueError('case-local dispatch full GO receipt required')
    receipt = json.loads(GO.read_text())
    if not (receipt.get('go') is True and receipt.get('host') == 'node0'
            and receipt.get('case_id') == 'SOLR-13'
            and receipt.get('mode') == 'full'
            and receipt.get('config_sha256') == metadata['config_sha256']
            and receipt.get('runner_sha256') == sha(Path(__file__))
            and receipt.get('intended_output') == str(OUT)):
        raise ValueError('dispatch full GO receipt absent or mismatched')
    if socket.gethostname().split('.', 1)[0] != 'node0' or OUT.exists():
        raise ValueError('node0 and a fresh exploratory full output are required')
    lock_root = Path('/tmp/mallory-lanes')
    lock_root.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ('zookeeper-node0-source.lock', 'solr-node0-v1.lock',
                     'solr-source-graphchecker-8.11.4.lock'):
            handle = (lock_root / name).open('a+')
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if OUT.exists() or shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError('fresh output and 7,650,410,496 free bytes required')
        available = next(int(row.split()[1]) for row in
                         Path('/proc/meminfo').read_text().splitlines()
                         if row.startswith('MemAvailable:'))
        if available < 8_388_608:
            raise ValueError('at least 8,388,608 KiB MemAvailable required')
        processes = subprocess.check_output(['ps', '-eo', 'user=,comm='], text=True)
        if any(row.split() == [getpass.getuser(), 'java']
               for row in processes.splitlines()):
            raise ValueError('another user JVM is running on node0')
        sys.path.insert(0, str(RELEASE))
        from Mallory.core import campaign  # noqa: E402
        if not Path(campaign.__file__).resolve().is_relative_to(RELEASE):
            raise ValueError('campaign core is not pinned')
        print(json.dumps({**metadata, 'status': 'live_gate_passed',
                          'admission_sha256': sha(GO), 'go': True},
                         sort_keys=True), flush=True)
        state = campaign.run(preflight.CONFIG, OUT)
    finally:
        for handle in reversed(handles):
            handle.close()
    print(json.dumps({'case_id': 'SOLR-13', 'status': state['status'],
                      'completed_trials': state['completed_trials'],
                      'elapsed_seconds': state['elapsed_seconds']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
