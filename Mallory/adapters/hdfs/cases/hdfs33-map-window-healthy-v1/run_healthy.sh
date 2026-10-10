#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != 1 || "$(hostname -s)" != node2 ]]; then
  echo "HDFS-33 healthy probe requires dispatch admission on node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs33-map-window-healthy-v1"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_out=/tmp/mallory-hdfs33-node2-map-window-healthy-v1
mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
if [[ -e "$task_out" ]]; then
  echo "Healthy output already exists: $task_out" >&2
  exit 2
fi
python3 -B "$task_here/preflight.py"
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_here/HDFS-33-node2-healthy-v1.json" \
  --out "$task_out" --calibration-only
