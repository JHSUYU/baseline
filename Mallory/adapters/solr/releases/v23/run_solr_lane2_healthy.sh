#!/usr/bin/env bash
set -euo pipefail

case_id=${1:?case ID required}
case "$case_id" in
  SOLR-19) config_sha=cea0846f606c04f99109705e528012b02eb6d122a1fd2b3970b362e6fda945a9 ;;
  SOLR-21) config_sha=dc7b9e864f715c1bb85dad233cdb7239de60339a1dd09ce4e6fba53870373705 ;;
  SOLR-38) config_sha=5d6c607255786b819a5a388c7a9fac385f5d64371e84776d898922c8919fe7fe ;;
  *) echo "unsupported case: $case_id" >&2; exit 2 ;;
esac

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$base/Mallory/adapters/solr/cases/$case_id/config-v23-lane2-calibration.json"
out="$base/data/mallory/calibration_v23_lane2/$case_id"
lock=/tmp/mallory-lanes/solr-lane2.lock

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
