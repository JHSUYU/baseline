#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
case_dir="$repo/Mallory/adapters/hbase/pilot/HBASE-31-typed-admission-v1"
release="$repo/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$case_dir/HBASE-31.dispatch-binding-v2.healthy.json"
output="$repo/data/mallory/calibration_v32_dispatch/HBASE-31"
worker_log="${output}.worker.log"

if [[ "$(hostname -s)" != node1 || "${MALLORY_HBASE31_NODE1_GRANT:-}" != healthy-v2 ]]; then
  printf 'HBASE-31 v2 requires a fresh dispatch grant on node1\n' >&2
  exit 75
fi

mkdir -p /tmp/mallory-lanes "$(dirname "$output")"
exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9 || { printf 'lane9-next is busy\n' >&2; exit 75; }
test ! -e "$output" && test ! -e "$worker_log"
python3 "$case_dir/preflight_v2.py" --allow-detached-source
cd "$repo"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
export PYTHONPATH="$release:$repo"

set +e
python3 -m Mallory.core.campaign --config "$config" --out "$output" --calibration-only >"$worker_log" 2>&1
campaign_code=$?
if [[ -e "$output/result.json" ]]; then
  printf '%s\n' "$campaign_code" >"$output/campaign-exit.txt"
  python3 -m Mallory.core.audit --campaign "$output" \
    --out "$output/offline-causal-audit.json" >>"$worker_log" 2>&1
  audit_code=$?
  printf '%s\n' "$audit_code" >"$output/audit-exit.txt"
else
  audit_code=1
fi
set -e

if [[ "$campaign_code" -ne 0 || "$audit_code" -ne 0 ]]; then
  printf 'HBASE-31 v2 healthy campaign or audit failed; inspect %s\n' "$worker_log" >&2
  exit 1
fi
python3 "$case_dir/verify_healthy.py" --binding-v2 --campaign "$output" \
  --out "$output/admission-verdict.json"
