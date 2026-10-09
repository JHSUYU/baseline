#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
overlay="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-hbase12-v1"
config="$overlay/cases/HBASE-12.scoped-healthy.json"
site="$overlay/cases/HBASE-12.sites.json"
jar="$overlay/releases/d02c2cb7ebace550/adapter.jar"
manifest="$overlay/releases/d02c2cb7ebace550/manifest.json"
output="$base/data/mallory/calibration_hbase12_scoped_graph_v1/HBASE-12"

if [[ ${MALLORY_HBASE12_SCOPED_GRANT:-} != healthy-only ]]; then
  printf 'HBASE-12 scoped run requires dispatch healthy-only grant\n' >&2
  exit 75
fi
exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'b70f84f80527c41f64e4f7b9e8e7b1bab1590792e3a44017e0e35decdcd0bbf6' "$config" \
  '73c179cad2950ab41aaa442c48b241279136e545bb2def7cfc4fb65c8da6c0bf' "$site" \
  'd02c2cb7ebace550532216ba9243fc1ab7e4cc4272b3c5192bb3b16ec057d247' "$jar" \
  '7ee7a210e4bdc9e5918678be3a2863dab8beade8691e68e40fc2dfd29d059244' "$manifest" \
  'a679d1d67144e41234b0af1e2cfd399d014dc13d99ba0acfe9ed8116258a6d15' "$release/manifest.json" \
  | sha256sum -c -
python3 "$overlay/cases/verify-stage.py"
export PYTHONPATH="$release:$base"
python3 -m Mallory.core.campaign --config "$config" --out "$output" --calibration-only
