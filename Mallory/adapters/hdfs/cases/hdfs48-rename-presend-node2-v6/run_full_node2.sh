#!/usr/bin/env bash
set -euo pipefail

if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "HDFS-48 v6 requires a separate dispatch GO" >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo "HDFS-48 v6 must run on node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v6"
task_v4="$task_base/Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v4"
task_out=/tmp/mallory-hdfs48-rename-presend-node2-full-v6
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 -B "$task_here/preflight.py"
python3 -B "$task_v4/preflight.py" --static
python3 -B "$task_v4/prepare_node2.py"
python3 -B "$task_here/preflight.py" --runtime
if [[ ! -e "$task_out" ]]; then
  python3 -B "$task_here/seed_continuation.py" --out "$task_out"
fi
cd /tmp
timeout --signal=TERM --kill-after=15s 3900s \
  python3 -B "$task_here/run_continuation.py" --out "$task_out"
python3 -B "$task_here/audit_terminal.py" \
  --out "$task_out" --report "$task_out/v6-strict-terminal-audit.json"
