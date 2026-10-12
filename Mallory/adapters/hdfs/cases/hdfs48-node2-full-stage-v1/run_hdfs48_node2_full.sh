#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-48 node2 full campaign requires dispatch admission" >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo "HDFS-48 node2 full campaign must run on node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_case="$task_base/Mallory/adapters/hdfs/cases/hdfs48-node2-full-stage-v1"
task_release="$task_base/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_case/preflight_hdfs48_node2_full.py"
cd /tmp
exec env PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_case/HDFS-48-node2-full-v1.json" \
  --out /tmp/mallory-hdfs48-original-v1-node2-full
