#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent
cd "$case_dir"

python3 - <<'PY'
import hashlib
import json
from pathlib import Path

root = Path('campaign')
summary = json.loads((root / 'candidate-0078-replay/summary.json').read_text())
rows = summary['replay_attempts']
if (len(rows) != 4 or summary['strict_replay_count'] != 4
        or summary['strict_exact_throw_replay_count'] != 0):
    raise SystemExit('trial 78 bounded replay review is incomplete')
if any(row['junit_exit'] != 0 or row['junit_gate'] != [1, 0, 0] for row in rows):
    raise SystemExit('trial 78 replay JUnit failure requires manual review')
current = (root / 'state.json').read_bytes()
frozen = (root / 'candidate-0078-checkpoint-state.json').read_bytes()
if hashlib.sha256(current).digest() != hashlib.sha256(frozen).digest():
    raise SystemExit('campaign checkpoint changed since trial 78 was frozen')
state = json.loads(current)
if state['status'] != 'candidate_target_exception' or len(state['completed']) != 78:
    raise SystemExit('not at reviewed trial 78 checkpoint')
print('trial 78 reviewed; resume exactly at trial 79', flush=True)
PY

python3 fuzz.py --max-trials 80 --max-faults 8 >> campaign/resume-79-80.log 2>&1
