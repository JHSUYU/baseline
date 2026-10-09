#!/usr/bin/env bash
set -u
set -o pipefail

lane_root=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next
release_root=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
case_config=$lane_root/runtime/configs/HBASE-35-lane9-next-mob-hbck-v2-healthy.json
case_output=$lane_root/healthy-HBASE-35-mob-hbck-v2
worker_log=$lane_root/runtime/HBASE-35-signature-v2-worker.log
worker_exit=$lane_root/runtime/HBASE-35-signature-v2-worker-exit.txt

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
if ! flock -n 9; then
  printf 'lane9-next lock busy\n' >&2
  exit 75
fi
if [[ -e "$case_output" || -e "$worker_log" || -e "$worker_exit" ]]; then
  printf 'HBASE-35 signature healthy output already exists\n' >&2
  exit 98
fi

export PYTHONPATH="$release_root:/users/ZhenyuLi/baseline"
python3 -m Mallory.core.campaign --config "$case_config" --out "$case_output" --calibration-only >"$worker_log" 2>&1
result=$?
printf '%s\n' "$result" >"$worker_exit"
exit "$result"
