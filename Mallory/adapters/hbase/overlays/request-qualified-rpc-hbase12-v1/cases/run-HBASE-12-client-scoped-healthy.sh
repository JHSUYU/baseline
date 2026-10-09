#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
overlay="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-hbase12-v1"
config="$overlay/cases/HBASE-12.client-scoped-healthy.json"
runner="$overlay/releases/51c53d7d45cd25ea/runner.jar"
manifest="$overlay/releases/51c53d7d45cd25ea/manifest.json"
adapter="$overlay/releases/d02c2cb7ebace550/adapter.jar"
healthy="$overlay/cases/scoped-healthy-positive-receipt.json"
output="$base/data/mallory/calibration_hbase12_client_scoped_v2/HBASE-12"

if [[ ${MALLORY_HBASE12_CLIENT_GRANT:-} != healthy-only ]]; then
  printf 'HBASE-12 client-bound run requires dispatch healthy-only grant\n' >&2
  exit 75
fi
exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '78b4843df6f8fa4828040a5bc9018b2b1aefa4cc9c2846bfa0e8f9904328bfd9' "$config" \
  '51c53d7d45cd25ea6071126f58e9dab2112a1138aecfb0ae2395a36bccac990f' "$runner" \
  '83d103c30b16a68fa08e80a58d5b08da0e749eaf86a8d6329b332f4f04334945' "$manifest" \
  'd02c2cb7ebace550532216ba9243fc1ab7e4cc4272b3c5192bb3b16ec057d247' "$adapter" \
  '2268b0261c4dd6c9238263b81cc4b03d6d086c38e2d4e4f830f1c5f9929f2fb2' "$healthy" \
  'a679d1d67144e41234b0af1e2cfd399d014dc13d99ba0acfe9ed8116258a6d15' "$release/manifest.json" \
  | sha256sum -c -
python3 "$overlay/cases/verify-client-stage.py"
export PYTHONPATH="$release:$base"
python3 -m Mallory.core.campaign --config "$config" --out "$output" --calibration-only
