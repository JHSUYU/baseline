#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-34 full campaign requires dispatch admission" >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo "HDFS-34 full campaign must run on node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_case="$task_base/Mallory/adapters/hdfs/cases/hdfs34-early-dn-full-v1"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 -B "$task_case/preflight.py"
cd /tmp
exec env PYTHONPATH="$task_base" python3 -B "$task_case/run_campaign.py"
