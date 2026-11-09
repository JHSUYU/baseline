#!/usr/bin/env bash
# wait_batch.sh <seconds> -- wait, then print every queue event since the start; return early on a failure.
f=/bulk/codingagent/logs/queue.log; n=$(wc -l < $f); end=$(( $(date +%s) + ${1:-1800} ))
while (( $(date +%s) < end )); do
  tail -n +$((n+1)) $f | grep -qE 'died|failed|needs-operator|all cases' && break
  sleep 30
done
tail -n +$((n+1)) $f
