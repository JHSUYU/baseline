#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/hbase/pilot/HBASE-12-normal-unassign-healthy-v1"
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$case_dir/HBASE-12.lane9-healthy.json"
site="$case_dir/HBASE-12.sites.json"
output="$base/data/mallory/calibration_v33/HBASE-12"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '9d9c3c9e9e78c6485637382d53c942b34bf86981fe11148baaa160601658d40c' "$config" | sha256sum -c -
printf '%s  %s\n' \
  '73c179cad2950ab41aaa442c48b241279136e545bb2def7cfc4fb65c8da6c0bf' "$site" | sha256sum -c -
python3 "$case_dir/verify_lane9_stage.py"
export PYTHONPATH="$release:$base"
python3 -m Mallory.core.campaign --config "$config" --out "$output"
