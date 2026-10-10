#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-48 heartbeat healthy admission requires dispatch GO" >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo "HDFS-48 heartbeat healthy admission must run on node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs48-heartbeat-response-node2-v2"
task_core="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_here/preflight.py"
cd /tmp
exec env PYTHONPATH="$task_core:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_here/HDFS-48-node2-healthy-v2.json" \
  --out /tmp/mallory-hdfs48-heartbeat-response-node2-healthy-v2
