#!/usr/bin/env bash
set -euo pipefail

BASE=/users/ZhenyuLi/baseline
ADAPTER="$BASE/Mallory/adapters/zookeeper"
CONFIG="$ADAPTER/cases/ZOOKEEPER-06-fa5f-ackepoch-retry-door-node1-healthy.json"
OUT="$BASE/data/mallory/calibration/ZOOKEEPER-06/ackepoch-retry-door-node1-healthy-v1"
LOCK=/tmp/mallory-lanes/zookeeper-node1-source.lock
CORE="$BASE/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"

mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || { echo 'ZooKeeper node1 source lane is occupied' >&2; exit 75; }
[[ ! -e "$OUT" ]] || { echo 'Healthy output already exists' >&2; exit 75; }

PYTHONPATH="$CORE:$BASE" python3 - "$CONFIG" "$ADAPTER/zookeeper-3.8.7-ackepoch-retry-door-node1-overlay.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

from Mallory.core.campaign import validate_config

config_path, receipt_path = map(Path, sys.argv[1:])
digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
if digest(config_path) != 'f336cc6c0d6f1e1f7a0ca16c03203d2cdbbccd7b5689f91db21cd930e6c6d725':
    raise SystemExit('Healthy config SHA changed')
if digest(receipt_path) != 'a34e86625873d356aa751a257476e318637e6af9d2f4842dda94ac3cda5af3fc':
    raise SystemExit('Compiled overlay receipt SHA changed')
config = json.loads(config_path.read_text())
receipt = json.loads(receipt_path.read_text())
validate_config(config)
if config['case_id'] != 'ZOOKEEPER-06' or not config['calibration_only']:
    raise SystemExit('Wrong case or mode')
if config['source_overlay_receipt_sha256'] != digest(receipt_path):
    raise SystemExit('Config overlay SHA mismatch')
for rel, expected in receipt['modified_files'].items():
    if digest(Path(receipt['patched_root']) / rel) != expected:
        raise SystemExit(f'Source SHA mismatch: {rel}')
for artifact in receipt['compiled_artifacts']:
    if digest(artifact['path']) != artifact['sha256']:
        raise SystemExit(f'Compiled artifact SHA mismatch: {artifact["path"]}')
for item in config['runtime_artifacts']:
    if digest(item['path']) != item['sha256']:
        raise SystemExit(f'Runtime artifact SHA mismatch: {item["path"]}')
if digest(Path(config['core_release']) / 'manifest.json') != '30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8':
    raise SystemExit('Core manifest SHA changed')
if digest(receipt['build_repair_receipt']) != receipt['build_repair_receipt_sha256']:
    raise SystemExit('Build repair receipt SHA mismatch')
if digest(receipt['compile_exit']) != receipt['compile_exit_sha256']:
    raise SystemExit('Compilation exit SHA mismatch')
if digest(receipt['compile_log']) != receipt['compile_log_sha256']:
    raise SystemExit('Compilation log SHA mismatch')
if digest(Path(receipt['patch_file'])) != receipt['patch_sha256']:
    raise SystemExit('Patch SHA mismatch')
print('ZK06 node1 healthy preflight passed:', len(receipt['compiled_artifacts']), 'compiled artifacts')
PY

PYTHONPATH="$CORE:$BASE" exec python3 -m Mallory.core.campaign \
  --config "$CONFIG" --out "$OUT" --calibration-only
