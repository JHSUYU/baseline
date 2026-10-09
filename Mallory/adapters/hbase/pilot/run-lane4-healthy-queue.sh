#!/usr/bin/env bash
set -euo pipefail

release=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
base=/users/ZhenyuLi/.mallory-worktrees/hbase/lane4

mkdir -p /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/hbase-lane4.lock
flock -n 9

export PYTHONPATH="$release:/users/ZhenyuLi/baseline"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"

cd "$release"
for case_id in HBASE-08 HBASE-13 HBASE-04; do
  config="$base/runtime/configs/$case_id-lane4-healthy.json"
  out="$base/healthy-$case_id"
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
    "HBASE-08": "44512d986bafbbf03aeba75982f48283078475888a695698f62ac6bff66593de",
    "HBASE-13": "6160839619803bccfcdff228a87ad3162031a922584f9a624f8058a796c71161",
    "HBASE-04": "6add5f266c4d3adca84a9d0a0b452a6c98fbe27b1a263eff696e0ed0436a6497",
}[config["case_id"]]
assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
assert config["calibration_only"] is True
validate_config(config)
verify_runtime_artifacts(config)
PY
  timeout 650s python3 -m Mallory.core.campaign --config "$config" --out "$out"
  python3 -m Mallory.core.audit --campaign "$out" --out "$out/offline-causal-audit.json"
done
