#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$base/Mallory/adapters/solr/cases/SOLR-10/config-v28-overseer-task-healthy.json"
site="$base/Mallory/adapters/solr/cases/SOLR-10/sites-v28-overseer-task.json"
adapter="$base/Mallory/adapters/solr/target/mallory-solr-adapter-v28.jar"
out="$base/data/mallory/calibration_v28_routed_alias/SOLR-10"
lock=/tmp/mallory-lanes/solr-routed-alias-v23.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 898a109273ca76a3d123cd2b8b7323297326dfab1f96333811ea89d45fd68031
test "$(sha256sum "$site" | cut -d ' ' -f1)" = d027ae65f30982d7755978fb571430290a13ccfbb64f47e11638b1f2e59f3e3c
test "$(sha256sum "$adapter" | cut -d ' ' -f1)" = 08ae3c1a584ae713581f1de5a30eb7df8b0cccd67e2f1147d231aa91a63e9285
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
