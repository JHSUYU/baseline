#!/usr/bin/env bash
set -euo pipefail

case_id=${1:?case ID required}
case "$case_id" in
  SOLR-21) config_sha=3c2ac978010294e645b45fc15dc2b5bb398836160aabfedf5abde30c8ed43add ;;
  SOLR-38) config_sha=a5a2e98eafe201dbb155e9cffcf1a1351f537d8d129ba89939f47eb09f85d588 ;;
  *) echo "unsupported case: $case_id" >&2; exit 2 ;;
esac

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$base/Mallory/adapters/solr/cases/$case_id/config-v24-lane1-calibration.json"
out="$base/data/mallory/calibration_v24_lane1/$case_id"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = "$config_sha"
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f
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
