#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$base/Mallory/adapters/solr/cases/SOLR-22/config-v27f-lane4-observed-full.json"
pilot="$base/data/mallory/pilot_v27p_lane4/SOLR-22/result.json"
out="$base/data/mallory/campaign_v27f_lane4/SOLR-22"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = c6cd8474ec262ab8655ed5dd872c72d19e9dd2fdca3b33c5cd4f975808608791
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f
test "$(sha256sum "$pilot" | cut -d ' ' -f1)" = cc2f7853d9f7902126830aec5ab20f9e82eed0cedb52a635b0450de2f655ae32
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
