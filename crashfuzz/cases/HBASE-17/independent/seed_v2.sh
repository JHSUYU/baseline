#!/usr/bin/env bash
set -u
case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-17/independent
suffix="${1:?seed suffix}"
mkdir -p "$case_dir/logs_v2"
bash "$case_dir/fuzz_v2.sh" run "$suffix" '' > "$case_dir/logs_v2/$suffix.log" 2>&1
code=$?
printf 'EXIT_CODE=%s\n' "$code" >> "$case_dir/logs_v2/$suffix.log"
exit "$code"
