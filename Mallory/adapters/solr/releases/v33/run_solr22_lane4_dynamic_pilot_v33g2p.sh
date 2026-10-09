#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/solr/cases/SOLR-22/config-v33g2p-lane4-fa5f-dynamic-actor-pilot.json"
out="$base/data/mallory/pilot_v33g2p_lane4/SOLR-22"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 94ad4bb7ab7641672470747dc1532fe58156f1707a1ed91601b3c8a4f0a9597e
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
assert config["calibration_only"] is False
assert "nodes" not in config["target"]
assert config["target_actor_binding_policy"]["calibration_only"] is False
assert config["target_actor_binding_policy"]["historical_actor_is_constraint"] is False
assert config["reject_coarse_roots"] is True
assert config["require_event_time_paths"] is True
assert config["budget"]["trials"] == 8
assert config["budget"]["max_faults_per_trial"] == 1
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
