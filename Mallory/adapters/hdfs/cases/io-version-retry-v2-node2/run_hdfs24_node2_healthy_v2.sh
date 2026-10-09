#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-24 node2 v2 requires dispatch admission" >&2
  exit 2
fi

task_root=/users/ZhenyuLi/baseline
task_case_dir="$task_root/Mallory/adapters/hdfs/cases/io-version-retry-v2-node2"
task_release="$task_root/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_output="$task_root/data/mallory/calibration_io_version_retry_v2_node2/HDFS-24"

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_case_dir/preflight_hdfs24_node2_v2.py"
cd /tmp
exec env PYTHONPATH="$task_release:$task_root" python3 -m Mallory.core.campaign \
  --config "$task_case_dir/HDFS-24-healthy-only-node2-v2.json" \
  --out "$task_output" --calibration-only
