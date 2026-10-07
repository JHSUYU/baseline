#!/usr/bin/env python3
"""Resume the checkpointed campaign only with node0 disk headroom."""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
STATE = HERE / 'campaign-state.json'
RESUME_FREE_BYTES = int(2.25 * (1 << 30))


def stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main() -> int:
    while True:
        state = json.loads(STATE.read_text())
        if state['finished']:
            print(stamp(), 'campaign finished', state.get('stop_reason'), flush=True)
            return 0
        if state.get('awaiting_extension_review') and not state.get('extension_decision'):
            print(stamp(), 'waiting for late-signal source review', flush=True)
            time.sleep(20)
            continue
        if state.get('pause_reason') == 'node0_resource_isolation_for_HBASE32U_s113_replay':
            print(stamp(), 'waiting for node0 isolation release', flush=True)
            time.sleep(20)
            continue
        free = shutil.disk_usage('/').free
        if free < RESUME_FREE_BYTES:
            print(stamp(), 'waiting for 2.25 GiB node0 free; current', free, flush=True)
            time.sleep(20)
            continue
        print(stamp(), 'resuming at', state['effective'], 'effective /',
              state['attempts'], 'attempts; free bytes', free, flush=True)
        result = subprocess.run([sys.executable, str(HERE / 'campaign.py')], cwd=HERE)
        if result.returncode:
            print(stamp(), 'campaign exited with error', result.returncode, flush=True)
            return result.returncode
        time.sleep(20)


if __name__ == '__main__':
    raise SystemExit(main())
