#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
runtime=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next/runtime
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$runtime/configs/HBASE-35-client-scan-door-v1-healthy.json"
output="$base/data/mallory/calibration_v29/HBASE-35"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '67a204538493b7ea34c2fadbd2645b80366e20067132b82b5564356103c2dda4' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 -m Mallory.core.campaign --config "$config" --out "$output"
