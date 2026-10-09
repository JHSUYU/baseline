#!/usr/bin/env bash
set -u
set -o pipefail

lane_root=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next
release_root=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
case_config=$lane_root/runtime/configs/HBASE-23-lane9-next-healthy-only.json
worker_log=$lane_root/runtime/HBASE-23-three-healthy-worker.log
worker_exit=$lane_root/runtime/HBASE-23-three-healthy-worker-exit.txt

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
if ! flock -n 9; then
  printf 'lane9-next lock busy\n' >&2
  exit 75
fi
if [[ -e "$worker_log" || -e "$worker_exit" ]]; then
  printf 'HBASE-23 repeat worker evidence already exists\n' >&2
  exit 98
fi

export PYTHONPATH="$release_root:/users/ZhenyuLi/baseline"
for index in 01 02 03; do
  case_output=$lane_root/healthy-HBASE-23-alt-5820-repeat$index
  if [[ -e "$case_output" ]]; then
    printf 'HBASE-23 repeat %s output already exists\n' "$index" >&2
    exit 98
  fi
  printf 'repeat=%s start\n' "$index" >>"$worker_log"
  python3 -m Mallory.core.campaign --config "$case_config" --out "$case_output" --calibration-only >>"$worker_log" 2>&1
  campaign_exit=$?
  python3 -m Mallory.core.audit --campaign "$case_output" --out "$case_output/offline-causal-audit.json" >>"$worker_log" 2>&1
  audit_exit=$?
  printf 'repeat=%s campaign_exit=%s audit_exit=%s\n' "$index" "$campaign_exit" "$audit_exit" >>"$worker_log"
  if python3 -c 'import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); r=json.loads((p/"result.json").read_text()); a=json.loads((p/"offline-causal-audit.json").read_text()); t=r["trials"][0]; sys.exit(0 if r["status"]=="calibration_complete" and t["junit_status"]=="passed" and t["target_reached"] and r["target_node_named"] and a["report_gate_passed"] and a["healthy_observed_path_doors"]>0 else 1)' "$case_output"; then
    printf 'repeat=%s qualified_healthy=true\n' "$index" >>"$worker_log"
    printf '0\n' >"$worker_exit"
    exit 0
  fi
  if [[ "$campaign_exit" != 0 && "$campaign_exit" != 2 ]]; then
    printf 'repeat=%s infrastructure_failure=true\n' "$index" >>"$worker_log"
    printf '%s\n' "$campaign_exit" >"$worker_exit"
    exit "$campaign_exit"
  fi
done
printf 'qualified_healthy=false repeats=3\n' >>"$worker_log"
printf '2\n' >"$worker_exit"
exit 2
