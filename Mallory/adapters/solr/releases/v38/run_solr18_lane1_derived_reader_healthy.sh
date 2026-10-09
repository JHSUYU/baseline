#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/solr/cases/SOLR-18/config-v38-lane1-fa5f-derived-reader-healthy.json"
out="$base/data/mallory/calibration_v38_lane1/SOLR-18"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 13e5bf5b7bdce68cf69185c0e933da49ff87e6cd3a8842336daab6b371e6ed59
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
assert config["hook_attestation_requirement"]["derive_reader_from_unique_registered_zkclient_and_fail_on_conflict"]
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
