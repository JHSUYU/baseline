#!/usr/bin/env bash
set -euo pipefail

release=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
base=/users/ZhenyuLi/.mallory-worktrees/hbase/lane6v2

mkdir -p /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/hbase-lane6v2.lock
flock -n 9

export PYTHONPATH="$release:/users/ZhenyuLi/baseline"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"

cd "$release"
for case_id in HBASE-19 HBASE-20 HBASE-21 HBASE-22; do
  config="$base/runtime/configs/$case_id-lane6v2-xerial-healthy.json"
  out="$base/healthy-$case_id-xerial"
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
    "HBASE-19": "ad9563a626c9aa8ad77d4de60ce2d9295dae97967468e6f70964dfa2a3340d7d",
    "HBASE-20": "d0d2e18ac1ebd9fc64f0871b780e052681629547ecc21ee654c6ba3d91fb23f8",
    "HBASE-21": "1f129e230aea9fa80d0e80a98981b15d70661526cb3d6923a2fc75031cbe9d71",
    "HBASE-22": "6ace5558f0119f05fc95f8ba757b7c786e751ee0085f4f3f47b7b52abba5434f",
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
