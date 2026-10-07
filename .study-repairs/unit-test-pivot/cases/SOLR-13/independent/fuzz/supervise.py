#!/usr/bin/env python3
"""Keep the SOLR-13 checklist row current while its tmux campaign runs."""

import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
PROGRESS = HERE / 'evidence/campaign/progress.json'
TERMINAL = {'budget_complete', 'queue_exhausted',
            'candidate_target_exception', 'attempt_cap_exhausted'}


def main() -> None:
    previous = None
    while True:
        if PROGRESS.is_file():
            progress = json.loads(PROGRESS.read_text())
            signature = (progress['attempted_plans'], progress['status'])
            if signature != previous:
                subprocess.run(['python3', str(HERE / 'sync_result.py')],
                               check=True)
                previous = signature
            if progress['status'] in TERMINAL:
                return
        live = subprocess.run(['tmux', 'has-session', '-t', 'solr13_fuzz'],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
        if not live:
            raise RuntimeError('SOLR-13 campaign tmux stopped before a terminal checkpoint')
        time.sleep(15)


if __name__ == '__main__':
    main()
