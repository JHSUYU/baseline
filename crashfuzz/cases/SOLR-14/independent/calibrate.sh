#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for n in 1 2; do
  out="$here/calibration/exists${n}-shard1"
  mkdir -p "$out"
  set +e
  python3 "$here/run.py" "$out" \
    --fault-plan "$here/calibration/exists${n}-shard1.properties" \
    > "$out/driver.log" 2>&1
  rc=$?
  set -e
  printf '%s\n' "$rc" > "$out/driver.exit"
done
