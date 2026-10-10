#!/usr/bin/env bash
set -euo pipefail

BASE=/users/ZhenyuLi/baseline
PKG="$BASE/Mallory/adapters/zookeeper/cases/ZOOKEEPER-06-ackepoch-retry-door-node0-v1"
CORE="$BASE/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG="$PKG/full.json"
OUT="$BASE/data/mallory/cases/ZOOKEEPER-06"
FLOOR=$((5 * 1024 * 1024 * 1024 + 600 * 1024 * 1024))

mkdir -p /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/zookeeper-node0-source.lock
flock -n 9 || { echo 'node0 source lane occupied' >&2; exit 75; }
[[ "$(sha256sum "$CONFIG" | cut -d' ' -f1)" == 70e5bad2926de79f85bbf2fe0d2c6b6772ec6ac192357bbf161819d5a1e52e53 ]] || exit 75
[[ "$(sha256sum "$CORE/manifest.json" | cut -d' ' -f1)" == 30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8 ]] || exit 75
if [[ -f "$OUT/result.json" ]] && python3 - "$OUT/result.json" <<'PY'
import json, sys
sys.exit(0 if json.load(open(sys.argv[1]))['status'] in {'budget_exhausted', 'queue_exhausted'} else 1)
PY
then
  echo 'terminal ZK06 campaign already exists; refusing duplicate run' >&2
  exit 75
fi
(( $(df -B1 --output=avail "$BASE" | tail -1) >= FLOOR )) || { echo 'disk below 5 GiB + 600 MiB floor' >&2; exit 75; }

export PYTHONPATH="$CORE:$BASE"
python3 "$PKG/verify.py" "$CONFIG"
export MALLORY_ATTEMPT_ID="zk06-node0-full-$(date -u +%Y%m%dT%H%M%SZ)"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$OUT/attempts"
set +e
python3 -m Mallory.core.campaign --config "$CONFIG" --out "$OUT" >>"$OUT/driver.log" 2>&1 &
controller=$!
while kill -0 "$controller" 2>/dev/null; do
  sleep 5
  available=$(df -B1 --output=avail "$BASE" | tail -1)
  if (( available < FLOOR )); then
    printf '{"attempt_id":"%s","available_bytes":%s,"floor_bytes":%s,"checked_utc":"%s"}\n' \
      "$MALLORY_ATTEMPT_ID" "$available" "$FLOOR" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$OUT/attempts/$MALLORY_ATTEMPT_ID.disk-floor.json"
    python3 - "$OUT/checkpoint.json" <<'PY'
import json, os, signal, sys
try:
    pid = json.load(open(sys.argv[1])).get('running', {}).get('pid')
    if isinstance(pid, int) and pid > 0:
        os.killpg(pid, signal.SIGTERM)
except (FileNotFoundError, ProcessLookupError, AttributeError):
    pass
PY
    kill -TERM "$controller" 2>/dev/null
    break
  fi
done
wait "$controller"
status=$?
set -e
finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '{"started_utc":"%s","finished_utc":"%s","exit_code":%d,"attempt_id":"%s","disk_floor_bytes":%s}\n' \
  "$started" "$finished" "$status" "$MALLORY_ATTEMPT_ID" "$FLOOR" > "$OUT/attempts/$MALLORY_ATTEMPT_ID.exit.json"
if (( status != 0 )); then
  exit "$status"
fi
python3 - "$OUT/result.json" <<'PY'
import json, sys
status = json.load(open(sys.argv[1]))['status']
if status not in {'budget_exhausted', 'queue_exhausted'}:
    raise SystemExit('ZK06 campaign did not reach a completion terminal: ' + status)
print('ZK06 terminal:', status)
PY
