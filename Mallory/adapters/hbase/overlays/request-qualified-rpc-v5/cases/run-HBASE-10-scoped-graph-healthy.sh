#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
overlay="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v5"
config="$overlay/cases/HBASE-10.scoped-graph-healthy.json"
output="$base/data/mallory/calibration_hbase10_scoped_graph_v4/HBASE-10"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'c753c7e9c281ea4f5fd6fb75533b9f67a75158f158490bfbbbc7f8538227ff87' "$config" \
  '71ed7ad90bd572af0f8bb4cf022b9dbc8dff424e8169eb70e6606a43f2151ffd' "$overlay/releases/71ed7ad90bd572af/adapter.jar" \
  'a679d1d67144e41234b0af1e2cfd399d014dc13d99ba0acfe9ed8116258a6d15' "$release/manifest.json" | sha256sum -c -
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
print('HBASE-10 graph-order healthy pins valid', flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output" --calibration-only
