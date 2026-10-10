#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-30 node2 full campaign requires dispatch admission" >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo "HDFS-30 node2 full campaign must run on node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_case="$task_base/Mallory/adapters/hdfs/cases/hdfs30-node2-full-stage-v2"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_case/preflight_hdfs30_node2_full.py"
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_case/HDFS-30-node2-full-v2.json" \
  --out /tmp/mallory-hdfs30-original-v2-node2-full
