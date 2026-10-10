#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_HDFS18_V3_NODE2_GRANT:-}" != "healthy-only" ]]; then
  echo "HDFS-18 node2 healthy-only dispatch grant required" >&2
  exit 2
fi
if [[ "$(hostname -s)" != node2 ]]; then
  echo "HDFS-18 v3 runner is scoped to node2" >&2
  exit 2
fi
task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs18-provided-heartbeat-v3"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_out=/tmp/mallory-hdfs18-provided-heartbeat-v3-node2-healthy
mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
if [[ -e "$task_out" ]]; then
  echo "Fresh healthy output already exists: $task_out" >&2
  exit 2
fi
python3 -B "$task_here/preflight.py"
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_here/HDFS-18-node2-healthy-v3.json" \
  --out "$task_out" --calibration-only
