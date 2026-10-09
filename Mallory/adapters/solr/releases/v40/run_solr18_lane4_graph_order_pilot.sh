#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
config="$base/Mallory/adapters/solr/cases/SOLR-18/config-v40p-lane4-graph-order-bounded-pilot.json"
out="$base/data/mallory/pilot_v40p_lane4/SOLR-18"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 61d9c6826deca90e0dcdab660fd1ba432820641adeb5f750e108f60de9bfa2bc
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["case_id"] == "SOLR-18"
assert config["calibration_only"] is False
assert config["auto_promote_if_healthy"] is True
assert config["budget"]["trials"] == 8
assert config["budget"]["max_faults_per_trial"] == 1
assert config["explore_outside_closure"] is False
assert config["require_event_time_paths"] is True
assert config["reject_coarse_roots"] is True
attestation = config["calibration_attestation"]
assert attestation["healthy_causal_audit"]["healthy_observed_path_doors"] == 17
assert attestation["healthy_junit"]["status"] == "passed"
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
