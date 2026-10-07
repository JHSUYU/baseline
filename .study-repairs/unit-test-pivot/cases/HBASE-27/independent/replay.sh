#!/usr/bin/env bash
set -u

here=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-27/independent
selector='ZK_RESPONSE~REGIONSERVER~/hbase/master~ZKNodeTracker.nodeCreated~1'
log="$here/logs/zk-master-rs-replay.log"
date -u +START_UTC=%Y-%m-%dT%H:%M:%SZ > "$log"
printf 'REQUESTED_SELECTOR=%s\n' "$selector" >> "$log"
HBASE27_TIMEOUT_SECONDS=120 bash "$here/run.sh" trial zk-master-rs-replay "$selector" >> "$log" 2>&1
code=$?
printf 'EXIT_CODE=%s\n' "$code" >> "$log"
date -u +END_UTC=%Y-%m-%dT%H:%M:%SZ >> "$log"
exit "$code"
