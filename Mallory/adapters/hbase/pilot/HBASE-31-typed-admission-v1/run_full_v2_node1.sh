#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
case_dir="$repo/Mallory/adapters/hbase/pilot/HBASE-31-typed-admission-v1"
release="$repo/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$case_dir/HBASE-31.dispatch-binding-v2.full.json"
output="$repo/data/mallory/cases/HBASE-31/campaigns/typed-dispatch-v2-full"
worker_log="${output}.worker.log"
disk_floor_bytes=$((7 * 1024 * 1024 * 1024))

if [[ "$(hostname -s)" != node1 || "${MALLORY_HBASE31_NODE1_GRANT:-}" != full-v2 ]]; then
  printf 'HBASE-31 full v2 requires an independent dispatch grant on node1\n' >&2
  exit 75
fi

mkdir -p /tmp/mallory-lanes "$(dirname "$output")"
exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9 || { printf 'lane9-next is busy\n' >&2; exit 75; }
test ! -e "$output" && test ! -e "$worker_log"
free_bytes=$(df -B1 --output=avail "$repo" | tail -1 | tr -d ' ')
if (( free_bytes < disk_floor_bytes )); then
  printf 'HBASE-31 full node1 disk gate held: %s bytes free\n' "$free_bytes" >&2
  exit 75
fi
python3 "$case_dir/preflight_full_v2.py" --allow-detached-source
cd "$repo"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
export PYTHONPATH="$release:$repo"

set +e
python3 -m Mallory.core.campaign --config "$config" --out "$output" >"$worker_log" 2>&1
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

if [[ "$campaign_code" -ne 0 || ( "$audit_code" -ne 0 && "$audit_code" -ne 2 ) ]]; then
  printf 'HBASE-31 full campaign or audit failed; inspect %s\n' "$worker_log" >&2
  exit 1
fi
python3 "$case_dir/verify_full_v2.py" --campaign "$output" \
  --out "$output/terminal-verdict.json"
