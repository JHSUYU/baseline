#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
overlay="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v5"
config="$overlay/cases/HBASE-10.scoped-graph-pilot.json"
healthy="$base/data/mallory/calibration_hbase10_scoped_graph_v4"
output="$base/data/mallory/pilots/HBASE-10-scoped-graph-v1"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '7fe2c9d26712d60f4bb117ad2dfb8c7794decd2aa3e6df6a8f5a81150522281c' "$config" \
  '71ed7ad90bd572af0f8bb4cf022b9dbc8dff424e8169eb70e6606a43f2151ffd' "$overlay/releases/71ed7ad90bd572af/adapter.jar" \
  'a679d1d67144e41234b0af1e2cfd399d014dc13d99ba0acfe9ed8116258a6d15' "$release/manifest.json" \
  '9beb7b55549657a11c67ed520589e78eb6f352107f5bdf1ecf771824f210d49d' "$healthy/HBASE-10-scoped-graph-positive-receipt.json" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config['calibration_only'] is False
assert config['budget'] == {'max_faults_per_trial': 1, 'seconds': 900,
                            'trial_timeout_seconds': 600, 'trials': 4}
assert config['require_event_time_paths'] is True
for artifact in config['runtime_artifacts']:
    path = Path(artifact['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
        raise SystemExit(f'runtime artifact SHA mismatch: {path}')
attestation = config['calibration_attestation']
for path, digest in (
    (Path(config['mapping']['verified_healthy_probe']),
     attestation['healthy_result_sha256']),
    (Path(attestation['healthy_causal_audit']['path']),
     attestation['healthy_causal_audit']['sha256']),
):
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SystemExit(f'healthy attestation SHA mismatch: {path}')
print('HBASE-10 scoped graph pilot pins valid', flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
