#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo 'HDFS-32 requires dispatch admission' >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo 'HDFS-32 must run on node2' >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs32-heartbeat-node2-full-v2"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_out=/tmp/mallory-hdfs32-heartbeat-node2-full-v2

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_here/preflight.py"
cd /tmp
set +e
PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_here/HDFS-32-node2-full-v2.json" --out "$task_out"
task_rc=$?
set -e
python3 "$task_here/collect_terminal.py" --case HDFS-32 --out "$task_out"
exit "$task_rc"
