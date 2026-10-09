#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v1/cases/HBASE-02.lane9-healthy.json"
output="$base/data/mallory/calibration_v30/HBASE-02"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'ed1f59b9d82b1f0cc19d55c13f7296225adb8ffeca4cfcb427ed55b5df4370e1' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 -m Mallory.core.campaign --config "$config" --out "$output"
