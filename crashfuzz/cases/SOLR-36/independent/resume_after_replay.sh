#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-36/independent
cd "$case_dir"

while tmux has-session -t solr36_replay_58 2>/dev/null; do
  sleep 15
done

python3 - <<'PY'
import json
from pathlib import Path
root=Path('campaign')
replay=json.loads((root/'candidate-0058-replay/summary.json').read_text())
rows=replay['replay_attempts']
if len(rows)<2 or replay['strict_replay_count']<2:
    raise SystemExit('bounded exact replay has not finished')
if any(row['junit_exit']!=0 or row['junit_gate']!=[1,0,0] for row in rows):
    raise SystemExit('replay JUnit failure needs source review before resumption')
state=json.loads((root/'state.json').read_text())
if state['status']!='candidate_target_exception' or len(state['completed'])!=58:
    raise SystemExit('candidate checkpoint changed; refuse automatic resume')
print('replay reviewed: original JUnit passed; resume at trial 59',flush=True)
PY

cp campaign/state.json campaign/candidate-0058-checkpoint-state.json
sha256sum campaign/candidate-0058-checkpoint-state.json > campaign/candidate-0058-checkpoint-sha256.txt
python3 fuzz.py --max-trials 80 --max-faults 8 >> campaign/resume-59-80.log 2>&1
