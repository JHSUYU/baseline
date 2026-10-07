#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent
cd "$case_dir"

python3 - <<'PY'
import hashlib
import json
from pathlib import Path

root = Path('campaign')
current = (root / 'state.json').read_bytes()
frozen = (root / 'milestone-0080/state.json').read_bytes()
if hashlib.sha256(current).digest() != hashlib.sha256(frozen).digest():
    raise SystemExit('80-trial checkpoint changed after frozen milestone')
state = json.loads(current)
if (state['status'] != 'budget_complete' or len(state['completed']) != 80
        or state['active'] is not None):
    raise SystemExit('expected exact 80-trial terminal checkpoint')
print('frozen 80-trial checkpoint verified; resume at 81', flush=True)
PY

python3 fuzz.py --max-trials 128 --max-faults 10 >> campaign/extend-81-128.log 2>&1
