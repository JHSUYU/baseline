#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v1/cases/HBASE-02.lane9-pilot.json"
output="$base/data/mallory/pilots/HBASE-02-qualified-get-v1"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'a8ac24493e44b4fcb2c03069c8de92eae80659b7f904e4575125af2bb830b0af' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 -m Mallory.core.campaign --config "$config" --out "$output"
