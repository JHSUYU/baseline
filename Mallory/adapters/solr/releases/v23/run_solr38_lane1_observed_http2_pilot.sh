#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$base/Mallory/adapters/solr/cases/SOLR-38/config-v24p-lane1-observed-http2-pilot.json"
out="$base/data/mallory/pilot_v24p_lane1/SOLR-38"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = adddb1f795628973807a6794019fe9dabd13f80c2d0dbd67034d8dcd6074cda4
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["budget"] == {"trials": 4, "seconds": 600,
                            "max_faults_per_trial": 1,
                            "trial_timeout_seconds": 480}
validate_config(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out"
