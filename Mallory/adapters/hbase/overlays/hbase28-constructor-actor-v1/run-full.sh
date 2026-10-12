#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
pack=$base/Mallory/adapters/hbase/overlays/hbase28-constructor-actor-v1
release=$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4
config=$pack/HBASE-28.constructor-actor-full.json
out=${1:?pass a new output directory}
lock=/tmp/mallory-lanes/hbase-lane9-next.lock

mkdir -p "$(dirname "$lock")"
exec 9>"$lock"
flock -n 9
test ! -e "$out"
python3 "$pack/verify_stage.py" --mode full
export PYTHONPATH="$release:$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
cd "$base"
python3 -m Mallory.core.campaign --config "$config" --out "$out"
