#!/usr/bin/env python3
"""Freeze the completed raw-sender pilot before changing HTTP identity semantics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / 'legacy-raw-sender-pilot'
FILES = ('solrsubshard-rpc-agent.jar', 'agent-build.json',
         'seed-audit.json', 'seed-selection.json')


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    if ARCHIVE.exists():
        raise RuntimeError(f'archive already exists: {ARCHIVE}')
    source = HERE / 'campaign'
    state = json.loads((source / 'state.json').read_text())
    if (state['budget'] != {'max_trials': 1, 'max_faults': 2}
            or len(state['completed']) != 1
            or state['completed'][0]['attempts'] != 2
            or state['completed'][0]['strict_injection']):
        raise RuntimeError('raw pilot checkpoint differs from audited 1/2 unmatched run')
    ARCHIVE.mkdir()
    source.rename(ARCHIVE / 'campaign')
    for name in FILES:
        shutil.copy2(HERE / name, ARCHIVE / name)
    inventory = {
        str(path.relative_to(ARCHIVE)): digest(path)
        for path in sorted(ARCHIVE.rglob('*')) if path.is_file()
    }
    (ARCHIVE / 'sha256-manifest.json').write_text(
        json.dumps({'classification': 'legacy_raw_sender_unmatched_pilot',
                    'selected_plans': 1, 'junit_attempts': 2,
                    'strict_injections': 0, 'postfault_target': 0,
                    'elapsed_seconds': state['completed'][0]['elapsed_seconds'],
                    'files': inventory}, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'archive': str(ARCHIVE),
                      'files': len(inventory),
                      'old_state_sha256': inventory['campaign/state.json']},
                     sort_keys=True))


if __name__ == '__main__':
    main()
