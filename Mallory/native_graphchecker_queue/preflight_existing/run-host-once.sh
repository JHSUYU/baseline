#!/usr/bin/env bash
set -euo pipefail

BASE=/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2
HOST=${1:-$(hostname -s)}
case "$HOST" in
  node0|node1|node2) ;;
  *) printf 'Unsupported physical host: %s\n' "$HOST" >&2; exit 2 ;;
esac
if [[ $(hostname -s) != "$HOST" ]]; then
  printf 'Owner host mismatch: expected %s, got %s\n' "$HOST" "$(hostname -s)" >&2
  exit 2
fi
cd "$BASE/python-snapshot-bind-v2"
export PYTHONPATH="$BASE/python-snapshot-bind-v2"
LOG_DIR="$BASE/state/.native-queue/controllers"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/${HOST}-$(date -u +%Y%m%dT%H%M%SZ).log"
set +e
python3 -m Mallory.native_graphchecker_queue run-host \
  --host "$HOST" --slots 2 \
  --inventory "$BASE/python-snapshot-bind-v2/Mallory/cases/inventory.json" \
  --ownership "$BASE/config/ownership.json" \
  --config-root "$BASE/config" \
  --state-root "$BASE/state" \
  --scratch-root "$BASE/scratch" \
  --results-dir "$BASE/results" \
  --isolation "$BASE/evidence/isolation.json" \
  --pilot-receipt "$BASE/state/.native-queue/pilot-ZOOKEEPER-07.json" \
  2>&1 | tee "$LOG"
CODE=${PIPESTATUS[0]}
set -e
printf 'run-host host=%s exit=%s log=%s\n' "$HOST" "$CODE" "$LOG"
exit "$CODE"
