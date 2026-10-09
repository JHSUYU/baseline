#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/c9ee501bdd73b45e356f7fea411f8754250eff8187567fa2e7b6be937cf7f24a"
config="$base/Mallory/adapters/solr/cases/SOLR-21/config-v25p-lane1-zkpath-pilot.json"
out="$base/data/mallory/pilot_v25p_lane1/SOLR-21"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = d5903d4887b266fe159ea9b3e7a5ae6c151ed2e1ad1b48f55034db233b9f7456
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 41522e5e82826fad8c1710ca1cb3ee3092be4895c39c96dd5fc92f455c4c8fe5
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["allow_local_timeline_doors"] is True
assert config["budget"] == {"trials": 8, "seconds": 900,
                            "max_faults_per_trial": 1,
                            "trial_timeout_seconds": 480}
validate_config(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
