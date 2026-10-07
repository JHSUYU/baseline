#!/usr/bin/env python3
"""Freeze diagnostic role seeds that may have added a lazy ZK lookup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / 'legacy-role-lazylookup-seeds'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    if ARCHIVE.exists():
        raise RuntimeError('diagnostic role-seed archive already exists')
    seeds = sorted(HERE.glob('healthy-role-[0-9][0-9]'))
    if len(seeds) < 2 or any(not (seed / 'run.json').is_file() for seed in seeds):
        raise RuntimeError('wait for all diagnostic JUnit seeds to complete')
    ARCHIVE.mkdir()
    for seed in seeds:
        seed.rename(ARCHIVE / seed.name)
    for name in ('seed-audit.json', 'seed-selection.json'):
        path = HERE / name
        if path.exists():
            path.rename(ARCHIVE / name)
    for name in ('agent-build.json', 'solrsubshard-rpc-agent.jar',
                 'src/research/solrsubshard/Probe.java', 'role-seeds.log'):
        path = HERE / name
        if path.exists():
            target = ARCHIVE / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    files = {str(path.relative_to(ARCHIVE)): sha(path)
             for path in sorted(ARCHIVE.rglob('*')) if path.is_file()}
    runs = [json.loads((ARCHIVE / seed.name / 'run.json').read_text())
            for seed in seeds]
    report = {'classification': 'diagnostic_role_seed_lazy_lookup_risk',
              'reason': ('ClusterState.getCollectionOrNull may resolve a '
                         'LazyCollectionRef through ZooKeeper; final role '
                         'agent must use non-lazy in-memory collection ref'),
              'runs': [seed.name for seed in seeds],
              'elapsed_seconds': round(sum(run['elapsed_seconds']
                                           for run in runs), 3),
              'files': files}
    (ARCHIVE / 'sha256-manifest.json').write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'archive': str(ARCHIVE), 'runs': report['runs'],
                      'elapsed_seconds': report['elapsed_seconds'],
                      'files': len(files)}, sort_keys=True))


if __name__ == '__main__':
    main()
