#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
config="$base/Mallory/adapters/solr/cases/SOLR-18/config-v44p-lane4-badversion-one-fault.json"
intent="$base/Mallory/adapters/solr/cases/SOLR-18/pilot-plan-intent-v44p.json"
out="$base/data/mallory/pilot_v44p_badversion_lane4/SOLR-18"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = c3caf1a7f3f22e0cd8981732d44d2e4cb5fba215bb2ae613b1d5a1d2181a9fff
test "$(sha256sum "$intent" | cut -d ' ' -f1)" = 7cc122b779f1da11ed5541530734e0a05af67082db12d79e813d275efc1d8f33
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" "$intent" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    intent = json.load(stream)
assert config["case_id"] == intent["case_id"] == "SOLR-18"
assert config["budget"]["trials"] == intent["fault_trial_count"] == 1
assert config["budget"]["max_faults_per_trial"] == intent["fault_count"] == 1
assert config["auto_promote_if_healthy"] is True
assert config["explore_outside_closure"] is True
assert config["agent_properties"]["auto.io.doors"] is False
assert config["source_backed_recovery_candidate"]["door_site"] == intent["site"]
assert config["source_backed_recovery_candidate"]["exception_class"] == intent["exception_class"]
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
