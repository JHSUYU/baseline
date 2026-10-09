#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
config="$base/Mallory/adapters/solr/cases/SOLR-18/config-v45-lane4-badversion-recovery-full.json"
out="$base/data/mallory/campaign_v45_badversion_lane4/SOLR-18"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 08e7dd68ac2b02a77a3f60240f4a1386efb2dae76186bf151be38dfc7dbb08dc
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config, verify_validated_recovery_sites
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["case_id"] == "SOLR-18"
assert config["budget"]["trials"] == 80
assert config["budget"]["seconds"] == 3600
assert config["budget"]["max_faults_per_trial"] == 6
assert config["single_fault_breadth_interval"] == 3
assert config["agent_properties"]["auto.io.doors"] is False
assert config["recovery_attestation"]["kind"] == "observed_program_order_and_region_parent_recovery_path"
assert len(config["validated_recovery_sites"]) == 1
validate_config(config)
verify_runtime_artifacts(config)
verify_validated_recovery_sites(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
