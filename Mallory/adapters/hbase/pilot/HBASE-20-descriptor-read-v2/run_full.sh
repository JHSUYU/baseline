#!/usr/bin/env bash
set -euo pipefail
if [[ "$(hostname -s)" != "node1" || "${MALLORY_HBASE20_NODE1_GRANT:-}" != "full-v2" ]]; then
  echo "HBASE-20 v2 requires node1 dispatch grant" >&2; exit 2
fi
base=/users/ZhenyuLi/baseline
stage="$base/Mallory/adapters/hbase/pilot/HBASE-20-descriptor-read-v2"
release="$base/Mallory/dispatch/releases/224e15f3a987faab681ec46278650cca80ee3bc34b75ea2f68c87b911f9928f1"
output="$base/data/mallory/HBASE-20/campaigns/descriptor-read-v2-full"
mkdir -p /tmp/mallory-lanes
exec 8>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 8
exec 9>/tmp/mallory-lanes/HBASE-20-descriptor-read-v2.lock
flock -n 9
python3 "$stage/preflight.py"
if [[ -e "$output" ]]; then
  echo "HBASE-20 v2 output already exists; explicit resume required" >&2; exit 2
fi
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
export PYTHONPATH="$release:$base"
exec python3 -m Mallory.core.campaign --config "$stage/HBASE-20.descriptor-read-v2.full.json" --out "$output"
