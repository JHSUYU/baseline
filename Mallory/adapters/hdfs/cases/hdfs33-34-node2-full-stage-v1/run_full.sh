#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-33/34 full campaign requires dispatch admission" >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo "HDFS-33/34 full campaign must run on node2" >&2
  exit 2
fi
case_id=${1:?case ID required}
if [[ "$case_id" != HDFS-33 && "$case_id" != HDFS-34 ]]; then
  echo "Only HDFS-33 or HDFS-34 is staged" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs33-34-node2-full-stage-v1"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_here/preflight.py" "$case_id"
case "$case_id" in
  HDFS-33) task_output=/tmp/mallory-hdfs33-node2-full-v1 ;;
  HDFS-34) task_output=/tmp/mallory-hdfs34-node2-full-v1 ;;
esac
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_here/$case_id-node2-full-v1.json" --out "$task_output"
