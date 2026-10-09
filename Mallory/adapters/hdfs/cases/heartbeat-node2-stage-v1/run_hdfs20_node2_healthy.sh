#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-20 node2 healthy run requires dispatch admission" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_case="$task_base/Mallory/adapters/hdfs/cases/heartbeat-node2-stage-v1"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_case/preflight_hdfs20_node2.py"
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_case/HDFS-20-healthy-only-node2.json" \
  --out /tmp/mallory-hdfs20-heartbeat-node2-v1-healthy \
  --calibration-only
