#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
case_dir="$repo/Mallory/adapters/hbase/pilot/HBASE-37-cluster-status-v1/full-v2"
release="$repo/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
output="$repo/data/mallory/cases/HBASE-37/campaigns/cluster-status-nonode-v2-full"
worker_log="${output}.worker.log"

if [[ "$(hostname -s)" != node1 || "${MALLORY_HBASE37_NODE1_GRANT:-}" != full-v2 ]]; then
  printf 'HBASE-37 full-v2 requires independent dispatch GO on node1\n' >&2
  exit 75
fi

mkdir -p /tmp/mallory-lanes "$(dirname "$output")"
exec 9>/tmp/mallory-lanes/hbase-lane7.lock
flock -n 9 || { printf 'HBase lane7 is busy\n' >&2; exit 75; }
exec 8>/tmp/mallory-lanes/hbase-lane7-next.lock
flock -n 8 || { printf 'HBase lane7-next is busy\n' >&2; exit 75; }
exec 7>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 7 || { printf 'HBase lane9-next is busy\n' >&2; exit 75; }

free_bytes=$(df -B1 --output=avail "$repo" | tail -1 | tr -d ' ')
if (( free_bytes < 7 * 1024 * 1024 * 1024 )); then
  printf 'HBASE-37 disk gate held: %s bytes free\n' "$free_bytes" >&2
  exit 75
fi
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
if (( available_kib < 6 * 1024 * 1024 )); then
  printf 'HBASE-37 memory gate held: %s KiB available\n' "$available_kib" >&2
  exit 75
fi
if pgrep -u "$(id -u)" -f 'edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit' >/dev/null; then
  printf 'Another selected HBase JUnit JVM owns node1\n' >&2
  exit 75
fi

site_path=/users/ZhenyuLi/.mallory-worktrees/hbase/lane7/runtime/cases/HBASE-37-nonode-full-v2/sites.json
if [[ -e "$site_path" ]]; then
  cmp -s "$case_dir/sites.json" "$site_path" || {
    printf 'Pinned HBASE-37 runtime site differs\n' >&2; exit 75;
  }
else
  install -D -m 0644 "$case_dir/sites.json" "$site_path"
fi
python3 "$case_dir/preflight.py" --node1
python3 "$repo/Mallory/dispatch/core_release.py" --verify "$release/manifest.json"
cd "$release"
export PYTHONPATH="$release"

if [[ ! -e "$output/checkpoint.json" ]]; then
  python3 -m Mallory.core.campaign --config "$case_dir/config.json" \
    --out "$output" --calibration-only >>"$worker_log" 2>&1
fi

python3 "$case_dir/healthy_gate.py" --campaign "$output" --promote \
  >>"$worker_log" 2>&1 || {
    printf 'HBASE-37 fresh healthy r0000 failed typed same-occurrence gate\n' >&2
    exit 75
  }
python3 "$case_dir/healthy_gate.py" --campaign "$output" --verify-promotion \
  >>"$worker_log" 2>&1

set +e
python3 -m Mallory.core.campaign --config "$case_dir/config.json" \
  --out "$output" >>"$worker_log" 2>&1
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
  printf 'HBASE-37 full-v2 controller or audit failed; inspect %s\n' "$worker_log" >&2
  exit 1
fi
python3 "$case_dir/verify_terminal.py" --campaign "$output"
