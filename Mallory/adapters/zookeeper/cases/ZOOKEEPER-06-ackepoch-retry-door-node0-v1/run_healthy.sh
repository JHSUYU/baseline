#!/usr/bin/env bash
set -euo pipefail

BASE=/users/ZhenyuLi/baseline
PKG="$BASE/Mallory/adapters/zookeeper/cases/ZOOKEEPER-06-ackepoch-retry-door-node0-v1"
CORE="$BASE/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG="$PKG/healthy.json"
OUT="$BASE/data/mallory/calibration/ZOOKEEPER-06/ackepoch-retry-door-node0-healthy-v1"
FLOOR=$((5 * 1024 * 1024 * 1024 + 600 * 1024 * 1024))

mkdir -p /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/zookeeper-node0-source.lock
flock -n 9 || { echo 'node0 source lane occupied' >&2; exit 75; }
[[ ! -e "$OUT" ]] || { echo 'node0 healthy output already exists' >&2; exit 75; }
[[ "$(sha256sum "$CONFIG" | cut -d' ' -f1)" == 6c94d0f1074dfdcba7467b57d51fd7a09eb8c96254a6ffe6be84bec126dc0f3c ]] || exit 75
[[ "$(sha256sum "$CORE/manifest.json" | cut -d' ' -f1)" == 30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8 ]] || exit 75
(( $(df -B1 --output=avail "$BASE" | tail -1) >= FLOOR )) || { echo 'disk below 5 GiB + 600 MiB floor' >&2; exit 75; }

export PYTHONPATH="$CORE:$BASE"
python3 "$PKG/verify.py" "$CONFIG"
export MALLORY_ATTEMPT_ID="zk06-node0-healthy-$(date -u +%Y%m%dT%H%M%SZ)"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$OUT"
set +e
python3 -m Mallory.core.campaign --config "$CONFIG" --out "$OUT" --calibration-only >"$OUT/driver.log" 2>&1
status=$?
set -e
printf '{"started_utc":"%s","finished_utc":"%s","exit_code":%d,"attempt_id":"%s"}\n' \
  "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" "$MALLORY_ATTEMPT_ID" > "$OUT/driver-exit.json"
exit "$status"
