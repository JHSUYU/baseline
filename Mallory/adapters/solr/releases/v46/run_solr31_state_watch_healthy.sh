#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
config="$base/Mallory/adapters/solr/cases/SOLR-31/config-v46-lane4-state-watch-healthy.json"
out="$base/data/mallory/calibration_v46_state_watch_lane4/SOLR-31"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 27872d651b3c6887809723c58e9b41c7bc9b238b7e2c10e97f3e5b5c472822d4
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["case_id"] == "SOLR-31"
assert config["calibration_only"] is True
assert config["agent_properties"]["auto.io.doors"] is False
assert config["source_backed_state_candidate"]["collection"] == "forceleader_lower_terms_collection"
assert config["source_backed_state_candidate"]["graph_edge_claim"] is False
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
