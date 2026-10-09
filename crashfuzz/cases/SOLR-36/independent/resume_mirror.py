#!/usr/bin/env python3
"""Reconnect the node0 checklist mirror after the bounded #58 replay."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
SSH = ('ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'ZhenyuLi@node2')
REMOTE = str(HERE / 'campaign/state.json')


def main() -> None:
    while True:
        result = subprocess.run((*SSH, 'cat ' + REMOTE),
                                capture_output=True, text=True)
        if result.returncode == 0:
            state = json.loads(result.stdout)
            if state['status'] == 'running' and len(state['completed']) >= 58:
                break
            if (state['status'] == 'candidate_target_exception'
                and len(state['completed']) > 58):
                raise RuntimeError('new candidate appeared before mirror reconnected')
        time.sleep(15)
    subprocess.run(('python3', str(HERE / 'mirror.py'), '--follow'), check=True)
    subprocess.run(('python3', str(HERE / 'finalize.py')), check=True)


if __name__ == '__main__':
    main()
