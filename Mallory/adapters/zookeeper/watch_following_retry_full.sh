#!/usr/bin/env bash
set -euo pipefail

if (( $# != 3 )); then
  printf 'usage: watch_following_retry_full.sh CAMPAIGN OUTPUT_RECEIPT CORE_RELEASE\n' >&2
  exit 2
fi
campaign=$1
receipt=$2
release=$3
base=/users/ZhenyuLi/baseline
mkdir -p "$(dirname "$receipt")"

for (( attempt=0; attempt<720; attempt++ )); do
  [[ -f "$campaign/driver-exit.json" ]] && break
  sleep 10
done
[[ -f "$campaign/driver-exit.json" ]] || { printf 'campaign did not exit within two hours\n' >&2; exit 124; }
python3 - "$campaign/driver-exit.json" <<'PY'
import json,sys
record=json.load(open(sys.argv[1],encoding="utf-8"))
if record["exit_code"] != 0:
    raise SystemExit(f"campaign exited {record['exit_code']}")
PY

export PYTHONPATH="$release:$base"
python3 -m Mallory.core.audit --campaign "$campaign" \
  --out "$campaign/offline-causal-audit.json"
python3 -m Mallory.adapters.zookeeper.audit_following_retry_campaign \
  "$campaign" "$receipt"
python3 - "$campaign" "$receipt" <<'PY'
import hashlib,json,sys
from pathlib import Path
campaign,receipt=map(Path,sys.argv[1:])
result=json.loads((campaign/"result.json").read_text())
audit=json.loads((campaign/"offline-causal-audit.json").read_text())
retry=json.loads(receipt.read_text())
if (result["status"] not in {"budget_exhausted","queue_exhausted"}
        or result["healthy_junit_validation"]["status"] != "passed"
        or result["runtime_attestation"]["valid"] is not True
        or audit["report_gate_passed"] is not True
        or retry["proven_postfault_path_trials"] < 1):
    raise SystemExit("full result needs manual quality review")
print(json.dumps({"case_id":result["case_id"],"status":result["status"],
                  "fault_trials_completed":result["fault_trials_completed"],
                  "strict_retry_path_trials":retry["proven_postfault_path_trials"],
                  "target_exception_trials":result["exact_exception_trials"],
                  "continuation_receipt_sha256":hashlib.sha256(receipt.read_bytes()).hexdigest()},
                 sort_keys=True))
PY
