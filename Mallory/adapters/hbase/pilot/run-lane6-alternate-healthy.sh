#!/usr/bin/env bash
set -euo pipefail

release=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
base=/users/ZhenyuLi/.mallory-worktrees/hbase/lane6

mkdir -p /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/hbase-lane6.lock
flock -n 9

export PYTHONPATH="$release:/users/ZhenyuLi/baseline"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"

cd "$release"
for case_id in HBASE-11 HBASE-19 HBASE-20 HBASE-21 HBASE-22; do
  config="$base/runtime/configs/$case_id-lane6-alternate-healthy.json"
  out="$base/healthy-$case_id-alternate"
  python3 - "$config" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

path = Path(sys.argv[1])
config = json.loads(path.read_text())
expected = {
    "HBASE-11": "3a1b50f0beb1bf8e4a9d42295451dd807a61b24a4083094c12cbaa6953f56f02",
    "HBASE-19": "9e28b8a5d8a7ffb2a21ad71ad73c0d33066dc0dc03d6a844406f3e56161489c2",
    "HBASE-20": "513db076c686511ede3522e83d89610b24a92d07c491e36cf3c62e4a927adbdb",
    "HBASE-21": "843916509fff80f6e8dc73ba49722ed1915f877f43d5d947dc6d25d29a8af6ca",
    "HBASE-22": "858b1b65e8e4dc9b2e7566a0af5e3d62d9bb9ed64c08107b07e3c5c45d0805fb",
}[config["case_id"]]
assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
assert config["calibration_only"] is True
validate_config(config)
verify_runtime_artifacts(config)
PY
  if timeout 780s python3 -m Mallory.core.campaign --config "$config" --out "$out"; then
    printf '%s calibration command completed\n' "$case_id"
  else
    printf '%s calibration command failed or timed out\n' "$case_id"
  fi
  if [[ -f "$out/result.json" ]]; then
    if python3 -m Mallory.core.audit --campaign "$out" --out "$out/offline-causal-audit.json"; then
      printf '%s causal audit passed\n' "$case_id"
    else
      printf '%s causal audit rejected quality\n' "$case_id"
    fi
  fi
done
