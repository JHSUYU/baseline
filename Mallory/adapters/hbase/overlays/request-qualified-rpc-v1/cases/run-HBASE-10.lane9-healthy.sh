#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v1/cases/HBASE-10.lane9-healthy.json"
output="$base/data/mallory/calibration_v31/HBASE-10"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'ea4e7dfc2292ef85020c3b5c7ab1f3b81e3b27688944a6b65e0c18d880385589' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 -m Mallory.core.campaign --config "$config" --out "$output"
