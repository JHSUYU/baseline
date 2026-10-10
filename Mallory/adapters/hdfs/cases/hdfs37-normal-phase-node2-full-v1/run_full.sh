#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_HDFS37_FULL_NODE2_GRANT:-}" != "1" ]]; then
  echo "HDFS-37 full node2 dispatch grant required" >&2
  exit 2
fi
if [[ "$(hostname -s)" != node2 ]]; then
  echo "HDFS-37 full runner is scoped to node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs37-normal-phase-node2-full-v1"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_out=/tmp/mallory-hdfs37-normal-node2-full-v1

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 -B "$task_here/preflight.py" --runtime
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_here/HDFS-37-node2-full-v1.json" --out "$task_out"
