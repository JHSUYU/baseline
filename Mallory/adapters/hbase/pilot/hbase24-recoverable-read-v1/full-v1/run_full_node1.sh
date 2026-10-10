#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
case_dir="$repo/Mallory/adapters/hbase/pilot/hbase24-recoverable-read-v1/full-v1"
release="$repo/Mallory/dispatch/releases/dc5ee9f0a9cb8dec77813d84389b36759068eabecee4bf74bc45c25afe2b0857"
config="$case_dir/config.json"
output="$repo/data/mallory/cases/HBASE-24/campaigns/recoverable-read-v1-full"
worker_log="${output}.worker.log"

if [[ "$(hostname -s)" != node1 || "${MALLORY_HBASE24_NODE1_GRANT:-}" != full-v1 ]]; then
  printf 'HBASE-24 full requires an independent dispatch GO on node1\n' >&2
  exit 75
fi

mkdir -p /tmp/mallory-lanes "$(dirname "$output")"
exec 9>/tmp/mallory-lanes/hbase-lane9.lock
flock -n 9 || { printf 'HBase lane9 is busy\n' >&2; exit 75; }
exec 8>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 8 || { printf 'HBase lane9-next is busy\n' >&2; exit 75; }
test ! -e "$output" && test ! -e "$worker_log"

free_bytes=$(df -B1 --output=avail "$repo" | tail -1 | tr -d ' ')
if (( free_bytes < 7 * 1024 * 1024 * 1024 )); then
  printf 'HBASE-24 disk gate held: %s bytes free\n' "$free_bytes" >&2
  exit 75
fi
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
if (( available_kib < 6 * 1024 * 1024 )); then
  printf 'HBASE-24 memory gate held: %s KiB available\n' "$available_kib" >&2
  exit 75
fi
if pgrep -u "$(id -u)" -f 'edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit' >/dev/null; then
  printf 'An HBase selected JUnit JVM is still active on node1\n' >&2
  exit 75
fi

python3 "$case_dir/preflight.py" --node1
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
  printf 'HBASE-24 full campaign or audit failed; inspect %s\n' "$worker_log" >&2
  exit 1
fi
python3 "$case_dir/verify_terminal.py" --campaign "$output"
