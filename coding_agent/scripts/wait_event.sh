#!/usr/bin/env bash
# wait_event.sh <timeout_s> -- block until the queue log records a finished agent, a validation or a failure.
f=/bulk/codingagent/logs/queue.log; n=$(wc -l < $f); end=$(( $(date +%s) + ${1:-3600} ))
while (( $(date +%s) < end )); do
  if tail -n +$((n+1)) $f | grep -qE 'agent (done|budget|error)|validation|died|failed|all cases'; then tail -n +$((n+1)) $f; exit 0; fi
  sleep 30
done
echo "timeout; no event"
