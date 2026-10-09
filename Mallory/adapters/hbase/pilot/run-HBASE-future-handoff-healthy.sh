#!/usr/bin/env bash
set -u
set -o pipefail

case_id=${1:?case ID required}
case "$case_id" in
  HBASE-07|HBASE-23) ;;
  *) printf 'unsupported case: %s\n' "$case_id" >&2; exit 64 ;;
esac

lane_root=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next
release_root=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f
case_config=$lane_root/runtime/configs/$case_id-lane9-next-future-handoff-healthy.json
case_output=$lane_root/healthy-$case_id-handoff-fa5f-v1
worker_log=$lane_root/runtime/$case_id-handoff-fa5f-worker.log
worker_exit=$lane_root/runtime/$case_id-handoff-fa5f-worker-exit.txt

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
if ! flock -n 9; then
  printf 'lane9-next lock busy\n' >&2
  exit 75
fi
if [[ -e "$case_output" || -e "$worker_log" || -e "$worker_exit" ]]; then
  printf 'future healthy output already exists: %s\n' "$case_output" >&2
  exit 98
fi

export PYTHONPATH="$release_root:/users/ZhenyuLi/baseline"
python3 -m Mallory.core.campaign --config "$case_config" --out "$case_output" --calibration-only >"$worker_log" 2>&1
result=$?
printf '%s\n' "$result" >"$worker_exit"
exit "$result"
