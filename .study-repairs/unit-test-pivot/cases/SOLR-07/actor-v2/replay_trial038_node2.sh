#!/usr/bin/env bash
set -u

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-07/actor-v2
cd "$case_dir" || exit 1
out="$case_dir/campaign/replay-trial-038-a"
mkdir -p "$out"
python3 run_v2.py "$out" --plan "$case_dir/campaign/trial-038/fault.properties" \
  > "$out/driver.log" 2>&1
status=$?
printf '%s\n' "$status" > "$out/driver.exit"
exit "$status"
