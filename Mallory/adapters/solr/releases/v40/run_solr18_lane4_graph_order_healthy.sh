#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
config="$base/Mallory/adapters/solr/cases/SOLR-18/config-v40-lane4-graph-order-healthy.json"
out="$base/data/mallory/calibration_v40_lane4/SOLR-18"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 32b4baa53ca837c18cf317044f0b78bff41c2af9c987631cbb65543a82fbbab5
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
