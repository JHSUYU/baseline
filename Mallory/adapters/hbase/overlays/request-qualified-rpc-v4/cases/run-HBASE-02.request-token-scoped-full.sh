#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/dc5ee9f0a9cb8dec77813d84389b36759068eabecee4bf74bc45c25afe2b0857"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v4/cases/HBASE-02.request-token-scoped-full.json"
receipt="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v4/cases/HBASE-02.request-token-scoped-pilot-receipt.json"
output="$base/data/mallory/HBASE-02/campaigns/request-token-scoped-v4-full"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '54a1a1a4be0a2cfe4ab36e14cefd73daec7931eb295957ec02ba57fb73c9d7e2' "$config" \
  '54081a2f31464a2ddee0759006c7cdcab1ea06a1ccdfdbee0d79a9e467ac1556' "$receipt" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" "$receipt" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config["mapping"]["status"] == "runtime_attested"
assert config["mapping"]["eligible_for_full_campaign"] is True
assert config["replay_identity_mode"] == "qualified_request_site"
assert config["budget"] == {"trials": 80, "seconds": 3600,
                            "max_faults_per_trial": 3, "trial_timeout_seconds": 600}
receipt = json.loads(Path(sys.argv[2]).read_text())
assert receipt["status"] == "pilot_strict_path_passed"
assert receipt["tamper_mutations_rejected"] == 4
for artifact in config["runtime_artifacts"]:
    path = Path(artifact["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise SystemExit(f"runtime artifact SHA mismatch: {path}")
audit = config["calibration_attestation"]["healthy_causal_audit"]
if hashlib.sha256(Path(audit["path"]).read_bytes()).hexdigest() != audit["sha256"]:
    raise SystemExit("healthy audit SHA mismatch")
print("HBASE-02 v4 scoped full artifacts and pilot receipt verified", flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
