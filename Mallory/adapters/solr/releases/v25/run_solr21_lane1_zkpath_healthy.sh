#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/c9ee501bdd73b45e356f7fea411f8754250eff8187567fa2e7b6be937cf7f24a"
config="$base/Mallory/adapters/solr/cases/SOLR-21/config-v25-lane1-zkpath-healthy.json"
out="$base/data/mallory/calibration_v25_lane1/SOLR-21"
lock=/tmp/mallory-lanes/solr-lane1.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = f5fac2aaf5e35c24499ddc9b48e75fb69f4deeb59dace581df9d9b7d28bde8e3
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
validate_config(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out" --calibration-only
