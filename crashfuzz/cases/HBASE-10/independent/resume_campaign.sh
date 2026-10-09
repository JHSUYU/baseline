#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-10/independent
cd "$case_dir"
if [[ -f campaign-state.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
state = json.loads(Path('campaign-state.json').read_text())
if state.get('coverage_scope_version') != 'hbase10_production_v1':
    raise SystemExit('refusing to resume a different coverage scope')
if state.get('stop_reason'):
    raise SystemExit('campaign already stopped: ' + state['stop_reason'])
PY
fi
./run.sh build
exec python3 -u campaign.py >> campaign.log 2>&1
