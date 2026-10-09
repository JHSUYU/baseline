#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-04/graphfree-validation
cd "$case_dir"
python3 - <<'PY'
import json
from pathlib import Path
state = json.loads(Path('campaign-state.json').read_text())
if state.get('coverage_scope_version') != 'hbase04_production_retry_v2':
    raise SystemExit('refusing to resume a different coverage scope')
if state.get('stop_reason'):
    raise SystemExit('campaign already stopped: ' + state['stop_reason'])
PY
./run.sh build-campaign
exec python3 -u campaign.py >> campaign.log 2>&1
