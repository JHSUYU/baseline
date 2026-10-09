#!/usr/bin/env python3
"""Replay one saved HBASE-37 fault plan without touching the campaign queue."""
import json
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
trial_id = sys.argv[1]
state = json.loads((here / 'checkpoint.json').read_text())
trial = next(t for t in state['trials'] if t['id'] == trial_id)
suffix = 'replay-' + trial_id
log = here / 'logs' / (suffix + '.log')
with log.open('w') as out:
    proc = subprocess.run(['bash', str(here / 'run.sh'), 'run', suffix,
                           ';'.join(trial['plan'])], stdout=out,
                          stderr=subprocess.STDOUT, check=False)
(here / 'logs' / (suffix + '.exit')).write_text(str(proc.returncode) + '\n')
