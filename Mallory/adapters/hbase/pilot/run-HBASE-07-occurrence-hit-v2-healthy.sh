#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
lane=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next
release=fc70357f631462023428f6dff385f56ef78188b52ef1a569e23dc1b9033855a4
config="$lane/runtime/configs/HBASE-07-stable-door-v2-occurrence-hit-healthy.json"
out="$repo/data/mallory/calibration_v26/HBASE-07"
lock=/tmp/mallory-lanes/hbase-lane9-next.lock

test ! -e "$out"
mkdir -p "$(dirname "$out")"
export PYTHONPATH="$repo/Mallory/dispatch/releases/$release:$repo"
python3 -m Mallory.dispatch.core_release --verify \
  "$repo/Mallory/dispatch/releases/$release/manifest.json"
exec flock -n "$lock" python3 -m Mallory.core.campaign \
  --config "$config" --out "$out" --calibration-only
