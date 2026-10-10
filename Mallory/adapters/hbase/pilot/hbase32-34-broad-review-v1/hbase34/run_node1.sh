#!/usr/bin/env bash
set -euo pipefail

mode=${1:-}
if [[ "$mode" != healthy && "$mode" != full ]]; then
  printf 'usage: %s healthy|full\n' "$0" >&2
  exit 64
fi

repo=/users/ZhenyuLi/baseline
case_dir="$repo/Mallory/adapters/hbase/pilot/hbase32-34-broad-review-v1/hbase34"
release="$repo/Mallory/dispatch/releases/dc5ee9f0a9cb8dec77813d84389b36759068eabecee4bf74bc45c25afe2b0857"
output="$repo/data/mallory/cases/HBASE-34/campaigns/broad-${mode}-v1"
log="${output}.worker.log"

if [[ "$(hostname -s)" != node1 || "${MALLORY_HBASE34_NODE1_GRANT:-}" != "$mode-v1" ]]; then
  printf 'HBASE-34 %s requires independent dispatch GO on node1\n' "$mode" >&2
  exit 75
fi
mkdir -p /tmp/mallory-lanes "$(dirname "$output")"
exec 9>/tmp/mallory-lanes/hbase-lane9.lock
flock -n 9 || { printf 'HBase lane9 busy\n' >&2; exit 75; }
exec 8>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 8 || { printf 'HBase lane9-next busy\n' >&2; exit 75; }

free_bytes=$(df -B1 --output=avail "$repo" | tail -1 | tr -d ' ')
(( free_bytes >= 7 * 1024 * 1024 * 1024 )) || { printf 'HBASE-34 disk gate held\n' >&2; exit 75; }
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
(( available_kib >= 6 * 1024 * 1024 )) || { printf 'HBASE-34 memory gate held\n' >&2; exit 75; }
if pgrep -u "$(id -u)" -f 'edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit' >/dev/null; then
  printf 'HBase selected JUnit JVM active\n' >&2
  exit 75
fi

python3 "$case_dir/preflight.py" --mode "$mode" --node1
cd "$repo"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
export PYTHONPATH="$release:$repo"

set +e
python3 -m Mallory.core.campaign --config "$case_dir/$mode.json" --out "$output" >"$log" 2>&1
campaign_code=$?
if [[ -f "$output/result.json" ]]; then
  printf '%s\n' "$campaign_code" >"$output/campaign-exit.txt"
  python3 -m Mallory.core.audit --campaign "$output" --out "$output/offline-causal-audit.json" >>"$log" 2>&1
  audit_code=$?
  printf '%s\n' "$audit_code" >"$output/audit-exit.txt"
else
  audit_code=1
fi
set -e

if [[ "$campaign_code" -ne 0 && "$campaign_code" -ne 2 ]]; then
  printf 'HBASE-34 %s campaign failed; inspect %s\n' "$mode" "$log" >&2
  exit 1
fi
if [[ "$audit_code" -ne 0 && "$audit_code" -ne 2 ]]; then
  printf 'HBASE-34 %s audit failed; inspect %s\n' "$mode" "$log" >&2
  exit 1
fi
python3 "$case_dir/summarize.py" --campaign "$output" --mode "$mode"
