#!/usr/bin/env python3
"""Pack complete original-JUnit raw evidence, excluding disposable scratch trees."""

import hashlib
import json
import subprocess
from pathlib import Path

from build import HERE

ARCHIVE = HERE / 'raw-evidence-v2.tar.zst'
MANIFEST = HERE / 'raw-evidence-v2.manifest.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not (HERE / 'campaign/summary-v2.json').is_file():
        raise RuntimeError('final campaign audit required before archiving')
    paths = []
    for name in ('build.json', 'agent-build.json', 'health-audit.json',
                 'node0-phase-audit.json', 'node2-health-audit.json',
                 'node0-orphan-trial16.tar.zst', 'solrcoord-actor-v2-agent.jar'):
        path = HERE / name
        if not path.is_file():
            raise RuntimeError(f'missing raw input: {name}')
        paths.append(path)
    for directory_name in ('clean-01', 'clean-02', 'healthy-01', 'healthy-02',
                           'node2-clean-01', 'node2-clean-02',
                           'node2-healthy-01', 'node2-healthy-02',
                           'campaign/trials'):
        directory = HERE / directory_name
        if not directory.is_dir():
            raise RuntimeError(f'missing raw directory: {directory_name}')
        paths.extend(path for path in directory.rglob('*') if path.is_file()
                     and 'scratch' not in path.relative_to(directory).parts)
    for name in ('campaign/state.json', 'campaign/progress.json',
                 'campaign/trial-ledger-v2.json', 'campaign/summary-v2.json',
                 'campaign/trial-ledger-at-80.json', 'campaign/summary-at-80.json',
                 'campaign/production-coverage-audit.json',
                 'campaign/production-coverage-at-80.json',
                 'campaign/state-at-80.json', 'campaign/progress-at-80.json',
                 'campaign/node2-run-80.exit', 'campaign/node2-run-80.log',
                 'campaign/node2-run-128.exit', 'campaign/node2-run-128.log'):
        path = HERE / name
        if not path.is_file():
            raise RuntimeError(f'missing audit input: {name}')
        paths.append(path)
    paths = sorted(set(paths))
    file_records = [{'path': str(path.relative_to(HERE)),
                     'bytes': path.stat().st_size, 'sha256': sha(path)} for path in paths]
    MANIFEST.write_text(json.dumps({'case_id': 'SOLR-34', 'schema': 1,
                                    'files': file_records}, indent=2, sort_keys=True) + '\n')
    relative = [str(path.relative_to(HERE)) for path in paths] + [MANIFEST.name]
    list_file = HERE / 'raw-evidence-v2.filelist'
    list_file.write_text('\n'.join(relative) + '\n')
    subprocess.run(['tar', '-I', 'zstd -3', '-cf', str(ARCHIVE), '-C', str(HERE),
                    '-T', str(list_file)], check=True)
    listing = subprocess.check_output(['tar', '-I', 'zstd', '-tf', str(ARCHIVE)], text=True)
    if set(listing.splitlines()) != set(relative):
        raise RuntimeError('archive listing differs from file manifest')
    receipt = {'archive': ARCHIVE.name, 'sha256': sha(ARCHIVE),
               'bytes': ARCHIVE.stat().st_size, 'file_count': len(relative)}
    (HERE / 'raw-evidence-v2.archive.json').write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
