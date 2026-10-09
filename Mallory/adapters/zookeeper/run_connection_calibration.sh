#!/usr/bin/env bash
set -euo pipefail

BASE=/users/ZhenyuLi/baseline
OUTPUT="$BASE/data/mallory/calibration/ZOOKEEPER-04/reconnect-healthy-v1"
LOCK=/tmp/mallory-lanes/zookeeper-lane2.lock
mkdir -p "$(dirname "$LOCK")" "$(dirname "$OUTPUT")"
exec 9>"$LOCK"
flock -n 9 || { echo 'ZooKeeper lane2 is occupied'; exit 75; }
python3 "$BASE/Mallory/adapters/zookeeper/prepare_connection_calibration.py" "$OUTPUT"
python3 "$BASE/Mallory/adapters/zookeeper/run_prepared.py" "$OUTPUT/command.json"
