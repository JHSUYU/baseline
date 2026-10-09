#!/usr/bin/env bash
set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
attempt=0
while true; do
  python3 -u "$here/run_campaign.py" >> "$here/worker.log" 2>&1
  status=$?
  if [ "$status" -eq 0 ]; then
    exit 0
  fi
  attempt=$((attempt + 1))
  printf '%s attempt=%s exit=%s; checkpoint retained\n' "$(date -u +%FT%TZ)" "$attempt" "$status" >> "$here/supervisor.log"
  if [ "$attempt" -ge 3 ]; then
    exit "$status"
  fi
  sleep 15
done
