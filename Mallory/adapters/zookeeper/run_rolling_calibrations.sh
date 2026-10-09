#!/usr/bin/env bash
set -uo pipefail

BASE=/users/ZhenyuLi/baseline
PREP="$BASE/Mallory/adapters/zookeeper/prepare_rolling_calibration.py"
RUN="$BASE/Mallory/adapters/zookeeper/run_prepared.py"
LOCK=/tmp/mallory-lanes/zookeeper-lane2.lock
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || { echo 'ZooKeeper lane2 is occupied'; exit 75; }

overall=0
for case_id in ZOOKEEPER-05 ZOOKEEPER-06 ZOOKEEPER-07; do
    output="$BASE/data/mallory/calibration/$case_id/rolling-healthy-v1"
    mkdir -p "$(dirname "$output")"
    if [[ -e "$output" ]]; then
        echo "Refusing to overwrite $output" >&2
        overall=1
        continue
    fi
    python3 "$PREP" "$case_id" "$output" || { overall=1; continue; }
    python3 "$RUN" "$output/command.json" || overall=1
done
exit "$overall"
