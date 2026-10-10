#!/usr/bin/env python3
"""Read-only SHA, source, budget, and restart checks for HDFS-34 full."""

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
HERE = Path(__file__).resolve().parent
CONFIG = HERE / 'HDFS-34-node2-full-v1.json'
OUTPUT = Path('/tmp/mallory-hdfs34-early-dn-v3-node2-full')
NODE2_SOURCE = Path('/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8')
STATIC_SOURCE = Path('/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2')
MIN_FREE_BYTES = 7_650_000_000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def require_sha(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f'missing or changed artifact: {path}')


def source_digest(root: Path, reference: dict) -> str:
    digest = hashlib.sha256()
    for relative in reference['paths']:
        path = root / relative
        if path.is_symlink():
            payload = b'L' + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b'F' + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f'missing pinned source: {path}')
        digest.update(os.fsencode(relative) + b'\0' + payload + b'\0')
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--static', action='store_true')
    args = parser.parse_args()
    if not args.static and socket.gethostname().split('.')[0] != 'node2':
        raise RuntimeError('runtime preflight is node2-only')

    manifest = json.loads((HERE / 'package-manifest.json').read_text())
    if manifest.get('case_id') != 'HDFS-34' or manifest.get('stage') != 'node2_full_pending_dispatch':
        raise RuntimeError('full package manifest changed')
    for name, expected in manifest['files'].items():
        require_sha(HERE / name, expected)
    if args.static:
        evidence = manifest['healthy_evidence']
        for kind in ('archive', 'receipt', 'result', 'offline_audit',
                     'observed_path_gate'):
            require_sha(BASE / evidence[kind], evidence[kind + '_sha256'])
    cfg = json.loads(CONFIG.read_text())
    if (cfg.get('case_id') != 'HDFS-34' or cfg.get('calibration_only') is not False or
            cfg.get('auto_promote_if_healthy') is not True or
            cfg.get('budget', {}).get('trials') != 80 or
            cfg['budget'].get('seconds') != 3600 or
            cfg['budget'].get('max_faults_per_trial') != 3 or
            cfg['budget'].get('trial_timeout_seconds') != 300 or
            cfg.get('require_event_time_paths') is not True or
            cfg.get('reject_coarse_roots') is not True or
            cfg.get('explore_outside_closure') is not False or
            cfg.get('cwd') != str(NODE2_SOURCE) or
            cfg.get('site_file') != str(HERE / 'HDFS-34.sites.json') or
            cfg.get('agent_properties', {}).get('adapter.jar') !=
            str(BASE / 'Mallory/adapters/hdfs/cases/hdfs34-early-dn-v3/release/adapter.jar')):
        raise RuntimeError('not the pinned HDFS-34 full campaign')
    sites = json.loads((HERE / 'HDFS-34.sites.json').read_text())
    if not any(row.get('method') == 'retrieveNamespaceInfo' and
               row.get('line') == 260 and row.get('exception_class') == 'java.io.IOException'
               for row in sites['doors']):
        raise RuntimeError('typed retrying RPC door missing')
    core = Path(cfg['core_release'])
    core_manifest = json.loads((core / 'manifest.json').read_text())
    for relative, expected in core_manifest['files'].items():
        require_sha(core / relative, expected)
    root = STATIC_SOURCE if args.static else NODE2_SOURCE
    for artifact in cfg['runtime_artifacts']:
        path = Path(artifact['path'])
        if args.static and path.is_relative_to(NODE2_SOURCE):
            path = root / path.relative_to(NODE2_SOURCE)
        require_sha(path, artifact['sha256'])
    reference = json.loads((BASE / 'Mallory/dispatch/source_reference.json').read_text())
    frozen = reference['roots']['/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3']
    if (frozen['commit'] != cfg['mapping']['source_commit'] or
            source_digest(root, frozen) != cfg['mapping']['node2_source_digest']):
        raise RuntimeError('Hadoop 3.4.3 source changed')
    sys.path[:0] = [str(core), str(BASE)]
    from Mallory.core.campaign import validate_config
    check_cfg = dict(cfg)
    check_cfg['cwd'] = str(root)
    validate_config(check_cfg)

    # Resume only the exact output/configuration already admitted. If r0000
    # was committed, its path proof must still be present and tied to bytes.
    if not args.static:
        if OUTPUT.exists():
            require_sha(OUTPUT / 'config.json', sha(CONFIG))
            checkpoint = json.loads((OUTPUT / 'checkpoint.json').read_text())
            if 0 in checkpoint.get('completed_trials', []):
                gate = json.loads((OUTPUT / 'healthy-gate.json').read_text())
                require_sha(OUTPUT / 'trials/r0000/result.json',
                            gate['fresh_result_sha256'])
                if not gate.get('passed'):
                    raise RuntimeError('existing full r0000 failed strict path gate')
        free = shutil.disk_usage(BASE).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f'node2 disk below HDFS reserve: {free}')
    print(json.dumps({'case_id': 'HDFS-34', 'status': 'static_preflight_pass'
                      if args.static else 'preflight_pass',
                      'full_config_sha256': sha(CONFIG), 'source_root': str(root),
                      'resuming': OUTPUT.exists() if not args.static else False},
                     sort_keys=True))


if __name__ == '__main__':
    main()
