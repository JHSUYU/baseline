#!/usr/bin/env bash
set -euo pipefail

BASE=/users/ZhenyuLi/baseline
CORE=5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
RELEASE="$BASE/Mallory/dispatch/releases/$CORE"
LOCK=/tmp/mallory-lanes/zookeeper-lane2.lock
OUT="$BASE/data/mallory/calibration_core5820"
mkdir -p "$OUT" "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || { echo 'ZooKeeper lane2 is occupied' >&2; exit 75; }

if (( $# == 0 )); then
    case_ids=(05 07)
else
    case_ids=("$@")
fi
for id in "${case_ids[@]}"; do
    [[ "$id" == 05 || "$id" == 07 ]] || { echo "Unsupported ZooKeeper case: $id" >&2; exit 2; }
    case_id="ZOOKEEPER-$id"
    config="$BASE/Mallory/adapters/zookeeper/cases/$case_id-5820-healthy.json"
    campaign="$OUT/$case_id"
    PYTHONPATH="$RELEASE:$BASE" python3 -m Mallory.core.campaign \
        --config "$config" --out "$campaign"
    PYTHONPATH="$RELEASE:$BASE" python3 -m Mallory.core.audit \
        --campaign "$campaign" --out "$campaign/offline-causal-audit.json"
    python3 - "$campaign" <<'PY'
import json
from pathlib import Path
import sys

directory = Path(sys.argv[1])
result = json.loads((directory / "result.json").read_text())
audit = json.loads((directory / "offline-causal-audit.json").read_text())
if not (result["status"] == "calibration_complete" and
        result["healthy_junit_validation"]["status"] == "passed" and
        result["runtime_attestation"]["valid"] is True and
        audit["report_gate_passed"] is True and
        audit["healthy_observed_path_doors"] > 0 and
        audit["healthy_closure_observed_edges"] > 0):
    raise SystemExit(f"{result['case_id']} did not pass observed-path admission")
print(result["case_id"], "healthy observed-path admission passed",
      audit["healthy_observed_path_doors"])
PY
done
