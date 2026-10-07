#!/usr/bin/env bash
set -u

here=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-27/independent

run_case() {
  local suffix="$1"
  local selector="$2"
  local log="$here/logs/$suffix.log"
  date -u +START_UTC=%Y-%m-%dT%H:%M:%SZ > "$log"
  printf 'REQUESTED_SELECTOR=%s\n' "$selector" >> "$log"
  HBASE27_TIMEOUT_SECONDS=120 bash "$here/run.sh" trial "$suffix" "$selector" >> "$log" 2>&1
  local code=$?
  printf 'EXIT_CODE=%s\n' "$code" >> "$log"
  date -u +END_UTC=%Y-%m-%dT%H:%M:%SZ >> "$log"
}

run_case zk-running-rs-pilot \
  'ZK_RESPONSE~REGIONSERVER~/hbase/running~ZKNodeTracker.nodeCreated~1'
run_case zk-master-getdata-rs-pilot \
  'ZK_RESPONSE~REGIONSERVER~/hbase/master~ZKNodeTracker.getData~1'
