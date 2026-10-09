#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/solr/cases/SOLR-01/config-v39-lane1-listaliases-healthy.json"
out="$base/data/mallory/calibration_v39_lane1/SOLR-01"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 2021a43a8aeb995f73c925bf1cf16948f065146632a4a0be194126870b4cf854
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["case_id"] == "SOLR-01"
assert config["calibration_only"] is True
assert config["reject_coarse_roots"] is True
assert config["require_event_time_paths"] is True
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
