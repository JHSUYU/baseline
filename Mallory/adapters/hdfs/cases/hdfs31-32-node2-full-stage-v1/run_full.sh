#!/usr/bin/env bash
set -euo pipefail

case_id="${1:-}"
case "$case_id" in
  HDFS-31|HDFS-32) ;;
  *) echo 'usage: run_full.sh HDFS-31|HDFS-32' >&2; exit 2 ;;
esac
if [[ "${MALLORY_DISPATCH_ADMITTED:-}" != "1" ]]; then
  echo "$case_id requires dispatch admission" >&2
  exit 2
fi
if [[ "$(hostname -s)" != "node2" ]]; then
  echo "$case_id must run on node2" >&2
  exit 2
fi

task_base=/users/ZhenyuLi/baseline
task_case="$task_base/Mallory/adapters/hdfs/cases/hdfs31-32-node2-full-stage-v1"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
task_out="/tmp/mallory-${case_id,,}-node2-full-v1"

mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9
python3 "$task_case/preflight.py" --case "$case_id"
cd /tmp
set +e
PYTHONPATH="$task_release:$task_base" python3 -m Mallory.core.campaign \
  --config "$task_case/$case_id-node2-full-v1.json" --out "$task_out"
task_campaign_rc=$?
set -e
python3 "$task_case/collect_terminal.py" --case "$case_id" --out "$task_out"
exit "$task_campaign_rc"
