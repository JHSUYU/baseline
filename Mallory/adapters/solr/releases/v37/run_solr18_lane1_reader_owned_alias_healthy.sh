#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/solr/cases/SOLR-18/config-v37-lane1-fa5f-reader-owned-alias-healthy.json"
out="$base/data/mallory/calibration_v37_lane1/SOLR-18"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 78b1acb8131a8c020d57a8e946bfbeb5cf2aa8d3b8112886bc299b451457ad25
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
assert config["calibration_only"] is True
assert config["reject_coarse_roots"] is True
assert config["require_event_time_paths"] is True
assert config["hook_attestation_requirement"]["registered_zk_state_reader_to_zk_client_unique_owner_before_watch_dispatch"]
assert config["hook_attestation_requirement"]["require_client_reader_registration_proof"]
assert config["hook_attestation_requirement"]["registered_alias_manager_enclosing_reader_owner"]
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
