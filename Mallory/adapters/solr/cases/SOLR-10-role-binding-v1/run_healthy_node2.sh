#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-10-role-binding-v1"
release="$base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$case_dir/config-role-v1-healthy-node2.json"
out="$base/data/mallory/calibration_solr10_role_v1_node2/SOLR-10"
lock=/tmp/mallory-lanes/solr-routed-alias-v23.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 74fbbbaabd7fa66fbd46884bc16c7021422e388b2bb2c19f3f017dc109abd637
test "$(sha256sum "$case_dir/releases/v1/mallory-agent.jar" | cut -d ' ' -f1)" = ef144323bc4bd2e7a231fc41ae35a7ec4255455146823ad177ebe3735f99ffb9
test "$(sha256sum "$case_dir/releases/v1/mallory-solr-adapter.jar" | cut -d ' ' -f1)" = 8dd63b244ea6073b7cabccf0d539076656a2197cf97dbf2778bef1dafbe3a7da
test "$(sha256sum "$release/manifest.json" | cut -d ' ' -f1)" = 101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"

python3 "$case_dir/run_pilot.py" SOLR-10 \
  --source /users/ZhenyuLi/.mallory-worktrees/solr-routed-alias-v23 \
  --output /tmp/mallory-solr10-role-preflight --preflight-only

PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["calibration_only"] is True
assert config["budget"]["trials"] == 1
validate_config(config)
verify_runtime_artifacts(config)
PY

exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 -m Mallory.core.campaign --config "$config" --out "$out" --calibration-only
