#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$base/Mallory/adapters/solr/cases/SOLR-22/config-v27-lane4-healthy.json"
out="$base/data/mallory/calibration_v27_lane4/SOLR-22"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 0788c38dc06b2e7b0a1c899466a9584d27eeb83938060b36b67a010eea08ef74
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["calibration_only"] is True
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out" --calibration-only
