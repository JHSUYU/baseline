#!/usr/bin/env bash
set -euo pipefail

case_id="${1:-}"
mode="${2:-}"
if [[ "$case_id" != HDFS-54 && "$case_id" != HDFS-55 ]] ||
   [[ "$mode" != healthy && "$mode" != full ]]; then
  echo 'usage: run_node2.sh HDFS-54|HDFS-55 healthy|full' >&2
  exit 2
fi
if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != 1 ]]; then
  echo 'explicit dispatch admission is required' >&2
  exit 2
fi
if [[ "$(hostname -s)" != node2 ]]; then
  echo 'known-control campaigns must run on node2' >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_case="$task_base/Mallory/adapters/hdfs/cases/known-controls-node2-v1"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_short="${case_id,,}"
task_short="${task_short//-/}"
task_output="/tmp/mallory-${task_short}-known-v1-node2-${mode}"

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_case/preflight.py" --case "$case_id" --mode "$mode"
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_case/${case_id}-node2-${mode}-v1.json" \
  --out "$task_output"
