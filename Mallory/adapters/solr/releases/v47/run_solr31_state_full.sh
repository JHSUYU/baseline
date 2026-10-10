#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
config="$base/Mallory/adapters/solr/cases/SOLR-31/config-v47-lane4-state-watch-full.json"
out="$base/data/mallory/campaign_v47_state_watch_lane4/SOLR-31"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 87d8a72d2ec1fda05f7cd3a19d77438997f5fd08e6b5e60f72798f23133f5f56
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config, verify_validated_recovery_sites
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["case_id"] == "SOLR-31"
assert config["budget"] == {"max_faults_per_trial": 3, "seconds": 3600,
                             "trial_timeout_seconds": 480, "trials": 80}
assert len(config["validated_recovery_sites"]) == 1
assert config["source_backed_state_candidate"]["graph_edge_claim"] is False
validate_config(config)
verify_runtime_artifacts(config)
verify_validated_recovery_sites(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
