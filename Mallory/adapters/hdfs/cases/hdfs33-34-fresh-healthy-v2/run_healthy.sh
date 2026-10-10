#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "Dispatch admission required" >&2
  exit 2
fi
case_id=${1:?case ID required}
if [[ "$case_id" != HDFS-33 && "$case_id" != HDFS-34 ]]; then
  echo "Only HDFS-33 and HDFS-34 healthy probes are staged" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs33-34-fresh-healthy-v2"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_out="/tmp/mallory-${case_id,,}-node2-fresh-healthy-v2"
mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
if [[ -e "$task_out" ]]; then
  echo "Fresh healthy output already exists: $task_out" >&2
  exit 2
fi
python3 -B "$task_here/preflight.py" "$case_id"
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_here/$case_id-node2-healthy-v2.json" \
  --out "$task_out" --calibration-only
