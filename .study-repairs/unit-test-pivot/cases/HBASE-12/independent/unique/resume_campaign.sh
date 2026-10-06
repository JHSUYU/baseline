#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-12/independent/unique
session=hbase12-unique-campaign
if tmux has-session -t "$session" 2>/dev/null; then
  printf '%s already running\n' "$session"
  exit 0
fi
if python3 - "$case_dir/campaign-state.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
if path.exists() and json.loads(path.read_text()).get("stop_reason"):
    sys.exit(0)
sys.exit(1)
PY
then
  printf '%s already reached a recorded stop condition\n' "$session"
  exit 0
fi
tmux new-session -d -s "$session" \
  "cd $case_dir && python3 -u campaign.py >> campaign.log 2>&1"
printf 'started %s from its checkpoint\n' "$session"
