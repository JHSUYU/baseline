#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
runtime=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next/runtime
release="$base/Mallory/dispatch/releases/96dd5cda2fe8e3f67130c8232fb98fa316a1eeac9a2ff3237075d7d8fe95538d"
config="$runtime/configs/HBASE-07-client-only-v1-pilot.json"
output="$base/data/mallory/pilots/HBASE-07-client-only-occurrence-hit-v1"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '3de87cd1fb3884389487ad15c65d259edecdc0ec4e1a89383dbffd0e10efca66' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 -m Mallory.core.campaign --config "$config" --out "$output"
