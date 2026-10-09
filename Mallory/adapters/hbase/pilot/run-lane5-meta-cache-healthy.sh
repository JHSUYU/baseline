#!/usr/bin/env bash
set -euo pipefail

release=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
base=/users/ZhenyuLi/.mallory-worktrees/hbase/lane5

mkdir -p /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/hbase-lane5.lock
flock -n 9

export PYTHONPATH="$release:/users/ZhenyuLi/baseline"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"

cd "$release"
for case_id in HBASE-29 HBASE-30; do
  config="$base/runtime/configs/$case_id-lane5-meta-cache-healthy.json"
  out="$base/healthy-$case_id-meta-cache"
  python3 - "$config" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

path = Path(sys.argv[1])
config = json.loads(path.read_text())
expected = {
    "HBASE-29": "8f275d10704745fb1a11048299fd5310d969d5caafdcb00a89ba4c778d1393d7",
    "HBASE-30": "4685c1dd0c113c006b991ed32ea7c257212db388643825034a3abd71c507de8f",
}[config["case_id"]]
assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
assert config["calibration_only"] is True
validate_config(config)
verify_runtime_artifacts(config)
PY
  timeout 780s python3 -m Mallory.core.campaign --config "$config" --out "$out"
  python3 -m Mallory.core.audit --campaign "$out" --out "$out/offline-causal-audit.json"
done
