#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/solr/cases/SOLR-01/config-v39f-lane1-listaliases-recovery-full.json"
out="$base/data/mallory/campaign_v39f_lane1/SOLR-01"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 59cf1fe3af5fa1beaab94944b447c9b8bc461a4224cc2227abfb201bc3e98528
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config, verify_validated_recovery_sites
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["case_id"] == "SOLR-01"
assert config["calibration_only"] is False
assert config["auto_promote_if_healthy"] is True
assert config["budget"]["trials"] == 80
assert config["budget"]["seconds"] == 3600
assert config["budget"]["max_faults_per_trial"] == 3
assert config["validated_recovery_exploration_interval"] == 5
assert config["single_fault_breadth_interval"] == 3
assert config["explore_outside_closure"] is True
assert config["require_event_time_paths"] is True
assert config["reject_coarse_roots"] is True
assert not config["static_fault_sites"]
assert config["mapping"]["status"] == "runtime_attested_recovery_seed"
assert config["recovery_attestation"]["terminal_quality_review_required"] is True
assert len(config["validated_recovery_sites"]) == 1
assert Path(config["recovery_attestation"]["pilot_receipt_path"]).is_file()
validate_config(config)
verify_runtime_artifacts(config)
verify_validated_recovery_sites(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
