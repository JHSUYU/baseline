#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
lane=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next
release=fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f
config="$lane/runtime/configs/HBASE-35-hbck-scanner-consume-v1-healthy.json"
out="$repo/data/mallory/calibration_v25/HBASE-35"
lock=/tmp/mallory-lanes/hbase-lane9-next.lock

test ! -e "$out"
mkdir -p "$(dirname "$out")"
export PYTHONPATH="$repo/Mallory/dispatch/releases/$release:$repo"
python3 -m Mallory.dispatch.core_release --verify \
  "$repo/Mallory/dispatch/releases/$release/manifest.json"
exec flock -n "$lock" python3 -m Mallory.core.campaign \
  --config "$config" --out "$out" --calibration-only
