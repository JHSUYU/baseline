#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/c9ee501bdd73b45e356f7fea411f8754250eff8187567fa2e7b6be937cf7f24a"
config="$base/Mallory/adapters/solr/cases/SOLR-21/config-v25f-lane1-zkpath-full.json"
out="$base/data/mallory/campaign_v25f_lane1/SOLR-21"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 310445778d94b1d40efd2452b8fe3113a576b521ed1d8c6054bad5392fcf796a
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 41522e5e82826fad8c1710ca1cb3ee3092be4895c39c96dd5fc92f455c4c8fe5
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["budget"] == {"trials": 80, "seconds": 3600,
                            "max_faults_per_trial": 6,
                            "trial_timeout_seconds": 480}
assert config["single_fault_breadth_interval"] == 3
assert config["allow_local_timeline_doors"] is True
validate_config(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
