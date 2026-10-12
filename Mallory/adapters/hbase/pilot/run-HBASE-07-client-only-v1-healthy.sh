#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
lane=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next
release=96dd5cda2fe8e3f67130c8232fb98fa316a1eeac9a2ff3237075d7d8fe95538d
config="$lane/runtime/configs/HBASE-07-client-only-v1-healthy.json"
out="$repo/data/mallory/calibration_v28/HBASE-07"
lock=/tmp/mallory-lanes/hbase-lane9-next.lock

test ! -e "$out"
mkdir -p "$(dirname "$out")"
export PYTHONPATH="$repo/Mallory/dispatch/releases/$release:$repo"
python3 -m Mallory.dispatch.core_release --verify \
  "$repo/Mallory/dispatch/releases/$release/manifest.json"
exec flock -n "$lock" python3 -m Mallory.core.campaign \
  --config "$config" --out "$out" --calibration-only
