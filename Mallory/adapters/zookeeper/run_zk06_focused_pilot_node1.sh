#!/usr/bin/env bash
set -euo pipefail

BASE=/users/ZhenyuLi/baseline
ADAPTER="$BASE/Mallory/adapters/zookeeper"
CONFIG="$ADAPTER/cases/ZOOKEEPER-06-fa5f-ackepoch-retry-door-node1-focused-pilot.json"
HEALTHY="$BASE/data/mallory/calibration/ZOOKEEPER-06/ackepoch-retry-door-node1-healthy-v1"
OUT="$BASE/data/mallory/pilots/ZOOKEEPER-06-ackepoch-retry-door-node1-v1"
CORE="$BASE/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
LOCK=/tmp/mallory-lanes/zookeeper-node1-source.lock

mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || { echo 'ZooKeeper node1 lane is occupied' >&2; exit 75; }
[[ ! -e "$OUT" ]] || { echo 'Focused pilot output already exists' >&2; exit 75; }
[[ "$(sha256sum "$CONFIG" | cut -d' ' -f1)" == 509eb7821842e46931fc6d5dfefc04647f3f804fce955996d8a5b74799936485 ]] || {
  echo 'Pilot config SHA changed' >&2; exit 75;
}
[[ "$(sha256sum "$CORE/manifest.json" | cut -d' ' -f1)" == 30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8 ]] || {
  echo 'Core release SHA changed' >&2; exit 75;
}

PYTHONPATH="$CORE:$BASE" exec python3 "$ADAPTER/run_zk06_focused_pilot.py" \
  --config "$CONFIG" --healthy "$HEALTHY" --out "$OUT"
