#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/2101b380daf3c963b13ad2ffe79ce6f30c9b33c5fedb46e227251f55f6558f5f"
config="$base/Mallory/adapters/solr/cases/SOLR-36/config-v21a-lane4-calibration.json"
out="$base/data/mallory/calibration_v21a_lane4/SOLR-36"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = b23b8bd879a99912f18b44a14cb0fbb1bcafe0f9206d3ec5294a5e6656d45cea
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 1fe02b6ae572811c988fa1fa4f569aee18b6907a21e07e1f7b2dbcac587d420d
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config

with open(sys.argv[1], encoding="utf-8") as stream:
    validate_config(json.load(stream))
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out" --calibration-only
