#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$base/Mallory/adapters/solr/cases/SOLR-19/config-v23b-lane2-promoted.json"
out="$base/data/mallory/campaign_v23b_lane2/SOLR-19"
lock=/tmp/mallory-lanes/solr-lane2.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 620a3b825a4a9007493b262b9c81ad501cc8ff5af1d4ff83ae798672e8d14a6f
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f
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
validate_config(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
