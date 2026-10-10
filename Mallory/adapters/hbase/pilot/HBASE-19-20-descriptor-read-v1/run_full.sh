#!/usr/bin/env bash
set -euo pipefail

case_number="${1:?usage: run_full.sh 19|20}"
case "$case_number" in
  19|20) ;;
  *) echo "case must be 19 or 20" >&2; exit 2 ;;
esac

base=/users/ZhenyuLi/baseline
stage="$base/Mallory/adapters/hbase/pilot/HBASE-19-20-descriptor-read-v1"
case_id="HBASE-$case_number"
config="$stage/$case_id.descriptor-read-v1.full.json"
output="$base/data/mallory/$case_id/campaigns/descriptor-read-v1-full"
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"

# Dispatch owns the node1 capacity and JVM gate. This lock prevents duplicate case controllers.
mkdir -p /tmp/mallory-lanes
exec 9>"/tmp/mallory-lanes/$case_id-descriptor-read-v1.lock"
flock -n 9

python3 "$stage/preflight.py" "$case_number"
if [[ -f "$output/result.json" ]]; then
  status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$output/result.json")"
  case "$status" in
    budget_exhausted|queue_exhausted)
      echo "$case_id already completed: $status" >&2
      exit 2 ;;
  esac
fi

cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
export PYTHONPATH="$release:$base"
exec python3 -m Mallory.core.campaign --config "$config" --out "$output"
