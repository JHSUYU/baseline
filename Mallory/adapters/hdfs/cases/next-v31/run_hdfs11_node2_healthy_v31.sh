#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-11 node2 v31 requires dispatch admission" >&2
  exit 2
fi

task_root=/users/ZhenyuLi/baseline
task_case_dir="$task_root/Mallory/adapters/hdfs/cases/next-v31"
task_release="$task_root/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_output="$task_root/data/mallory/calibration_v31_node2/HDFS-11"

# Hold the same lock used by the earlier node2 HDFS work for the whole trial.
exec 9>"$task_lock"
flock -n 9
python3 "$task_case_dir/preflight_hdfs11_node2_v31.py"
cd /tmp
exec env PYTHONPATH="$task_release:$task_root" python3 -m Mallory.core.campaign \
  --config "$task_case_dir/HDFS-11-long-lived-key-update-healthy-node2-v31.json" \
  --out "$task_output" --calibration-only
