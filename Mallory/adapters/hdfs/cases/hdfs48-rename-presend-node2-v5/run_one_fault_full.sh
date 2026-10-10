#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-48 v5 requires a separate dispatch GO" >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo "HDFS-48 v5 must execute on node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v5"
task_v4="$task_base/Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v4"
task_core="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_out=/tmp/mallory-hdfs48-rename-presend-node2-full-v5
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 -B "$task_here/preflight.py"
python3 -B "$task_v4/preflight.py" --static
python3 -B "$task_v4/prepare_node2.py"
python3 -B "$task_here/preflight.py" --runtime
cd /tmp
env PYTHONPATH="$task_core:$task_base" timeout --signal=TERM --kill-after=15s 480s \
  python3 -B -m Mallory.core.campaign \
    --config "$task_here/HDFS-48-node2-one-fault-full-v5.json" \
    --out "$task_out"
python3 -B "$task_here/audit_full.py" \
  --campaign "$task_out" --out "$task_out/v5-strict-audit.json"
