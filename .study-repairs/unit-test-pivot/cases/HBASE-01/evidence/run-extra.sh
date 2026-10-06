#!/usr/bin/env bash
set -u

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-01/work
printf '%s\n' "START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$case_dir/extra-times.log"

for item in timeout02 double03; do
  case "$item" in
    timeout02) plan="$case_dir/fault-plan-timeout-02.json" ;;
    double03) plan="$case_dir/fault-plan-double-03.json" ;;
  esac
  printf '%s\n' "$item START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$case_dir/extra-times.log"
  bash "$case_dir/run.sh" run "$item" "$plan" > "$case_dir/$item.log" 2>&1
  run_exit=$?
  printf '%s\n' "$run_exit" > "$case_dir/$item.exit"
  if [[ "$run_exit" -eq 0 ]]; then
    bash "$case_dir/run.sh" aggregate "$item" > "$case_dir/aggregate-$item.log" 2>&1
    printf '%s\n' "$?" > "$case_dir/aggregate-$item.exit"
  fi
  printf '%s\n' "$item END_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ) EXIT=$run_exit" >> "$case_dir/extra-times.log"
done

printf '%s\n' "END_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$case_dir/extra-times.log"
