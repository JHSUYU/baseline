#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/solr/cases/SOLR-01/config-v39p-lane1-listaliases-recovery-pilot.json"
out="$base/data/mallory/pilot_v39p_lane1/SOLR-01"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 18ba3eca50a5d73cfcd5030bd8a57c4f2c184096788f05bf5b71f4f0f3000446
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
assert config["calibration_only"] is False
assert config["auto_promote_if_healthy"] is True
assert config["budget"]["trials"] == 5
assert config["budget"]["max_faults_per_trial"] == 1
assert config["static_fault_sites"] == ["org.apache.solr.client.solrj.impl.BaseHttpClusterStateProvider#getAliases(Z)Ljava/util/Map;@247:door:1"]
assert config["reject_coarse_roots"] is True
assert config["require_event_time_paths"] is True
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
