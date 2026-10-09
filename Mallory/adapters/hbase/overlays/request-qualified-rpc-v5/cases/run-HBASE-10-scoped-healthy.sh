#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
overlay="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v5"
config="$overlay/cases/HBASE-10.scoped-healthy.json"
output="$base/data/mallory/calibration_hbase10_scoped_v3/HBASE-10"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '26c64b58d3b5f767e7a240a6c1c95ba17ec40cae33767a133e5a4cbbdf9def55' "$config" \
  '71ed7ad90bd572af0f8bb4cf022b9dbc8dff424e8169eb70e6606a43f2151ffd' "$overlay/releases/71ed7ad90bd572af/adapter.jar" \
  '85a574186e772d3320a37cc290e3bc73c7cdca70455b726c7b4aa2589d926573' "$overlay/releases/71ed7ad90bd572af/manifest.json" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config['calibration_only'] is True
assert config['budget']['trials'] == 1
assert config['require_event_time_paths'] is True
assert config['mapping']['fault_admission_blocked'] is True
for artifact in config['runtime_artifacts']:
    path = Path(artifact['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
        raise SystemExit(f'runtime artifact SHA mismatch: {path}')
print('HBASE-10 scoped healthy pins valid', flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output" --calibration-only
