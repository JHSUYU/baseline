#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-04/graphfree-validation
state=/users/ZhenyuLi/baseline/crashfuzz/hbase04/phase2/state.json

for ((poll=0; poll<240; poll++)); do
  stop_reason=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("stop_reason", ""))' "$state")
  if [[ "$stop_reason" == budget_reached ]]; then
    break
  fi
  if [[ -n "$stop_reason" ]]; then
    printf 'SKIP independent replay: phase 2 stopped with %s\n' "$stop_reason"
    exit 1
  fi
  sleep 30
done

if [[ "$stop_reason" != budget_reached ]]; then
  printf 'SKIP independent replay: phase 2 has not completed after polling window\n'
  exit 1
fi

"$case_dir/run.sh" build

run_case() {
  local name=$1
  shift
  printf 'START %s %s\n' "$name" "$(date -u +%FT%TZ)"
  local rc
  if "$case_dir/run.sh" run "$name" "$@" > "$case_dir/$name.log" 2>&1; then
    rc=0
  else
    rc=$?
  fi
  printf '%s\n' "$rc" > "$case_dir/$name.exit"
  if [[ -f "$case_dir/$name.exec" ]]; then
    "$case_dir/run.sh" coverage "$name" > "$case_dir/$name.coverage" 2>&1 || true
  fi
  printf 'END %s exit=%s %s\n' "$name" "$rc" "$(date -u +%FT%TZ)"
}

run_case healthy
run_case read_io_0 0 1 IOException
run_case read_timeout_0 0 1 SocketTimeoutException
run_case read_io_1 1 1 IOException
run_case read_retry_pair -1 -1 '' '0:1:IOException,0:3:IOException'
printf 'DONE independent graph-free representative replay\n'
