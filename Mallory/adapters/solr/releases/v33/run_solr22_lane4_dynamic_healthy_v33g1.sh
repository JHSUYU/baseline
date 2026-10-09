#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/solr/cases/SOLR-22/config-v33g1-lane4-fa5f-dynamic-actor-healthy.json"
out="$base/data/mallory/calibration_v33g1_lane4/SOLR-22"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 009cb27984d1d6c36e419fb4e134aafb3d9a4352b0ebc57202291100e082c737
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["case_id"] == "SOLR-22"
assert config["calibration_only"] is True
assert "nodes" not in config["target"]
assert config["reject_coarse_roots"] is True
assert config["require_event_time_paths"] is True
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
