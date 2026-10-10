#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
case_dir="$repo/Mallory/adapters/hbase/overlays/hbase28-constructor-actor-v1/nonloopback-master-full-v2"
release="$repo/Mallory/dispatch/releases/224e15f3a987faab681ec46278650cca80ee3bc34b75ea2f68c87b911f9928f1"
output="$repo/data/mallory/cases/HBASE-28/campaigns/nonloopback-master-full-v2"
worker_log="${output}.worker.log"

if [[ "$(hostname -s)" != node1 || "${MALLORY_HBASE28_NODE1_GRANT:-}" != full-v2 ]]; then
  printf 'HBASE-28 full-v2 requires dispatch GO on node1\n' >&2
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
(( free_bytes >= 7 * 1024 * 1024 * 1024 )) || { printf 'HBASE-28 disk gate held\n' >&2; exit 75; }
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
(( available_kib >= 6 * 1024 * 1024 )) || { printf 'HBASE-28 memory gate held\n' >&2; exit 75; }
if pgrep -u "$(id -u)" -f 'edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit' >/dev/null; then
  printf 'Another selected HBase JUnit owns node1\n' >&2
  exit 75
fi
if [[ -e "$output" ]]; then
  printf 'HBASE-28 full-v2 output already exists; no duplicate launch\n' >&2
  exit 75
fi
python3 "$case_dir/preflight.py" --node1
python3 "$repo/Mallory/dispatch/core_release.py" --verify "$release/manifest.json"
cd "$release"
export PYTHONPATH="$release"
python3 -m Mallory.core.campaign --config "$case_dir/config.json" \
  --out "$output" --calibration-only >>"$worker_log" 2>&1
python3 "$case_dir/healthy_gate.py" --campaign "$output" --promote \
  >>"$worker_log" 2>&1 || {
    printf 'HBASE-28 fresh healthy r0000 failed exact typed gate\n' >&2
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
  printf 'HBASE-28 controller or audit failed; inspect %s\n' "$worker_log" >&2
  exit 1
fi
python3 "$case_dir/verify_terminal.py" --campaign "$output"
