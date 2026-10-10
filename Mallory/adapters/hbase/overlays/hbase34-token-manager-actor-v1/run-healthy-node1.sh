#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
case_dir="$repo/Mallory/adapters/hbase/overlays/hbase34-token-manager-actor-v1"
output="$repo/data/mallory/calibration_hbase34_token_manager_actor_v4/HBASE-34"
log="${output}.worker.log"

if [[ "$(hostname -s)" != node1 ||
      "${MALLORY_HBASE34_V4_NODE1_GRANT:-}" != healthy-only ]]; then
  printf 'HBASE-34 v4 requires an explicit node1 healthy-only lane grant\n' >&2
  exit 75
fi
mkdir -p /tmp/mallory-lanes "$(dirname "$output")"
exec 9>/tmp/mallory-lanes/hbase-lane9.lock
flock -n 9 || { printf 'HBase lane9 busy\n' >&2; exit 75; }
exec 8>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 8 || { printf 'HBase lane9-next busy\n' >&2; exit 75; }
[[ ! -e "$output" ]] || { printf 'HBASE-34 v4 output already exists\n' >&2; exit 75; }
free_bytes=$(df -B1 --output=avail "$repo" | tail -1 | tr -d ' ')
(( free_bytes >= 7 * 1024 * 1024 * 1024 )) || {
  printf 'HBASE-34 v4 disk gate held\n' >&2; exit 75;
}
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
(( available_kib >= 6 * 1024 * 1024 )) || {
  printf 'HBASE-34 v4 memory gate held\n' >&2; exit 75;
}
if pgrep -u "$(id -u)" -f 'edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit' >/dev/null; then
  printf 'HBase selected JUnit JVM active\n' >&2
  exit 75
fi

python3 "$case_dir/preflight.py" --verify-prior-evidence
cd "$repo"
release=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["core_release"])' \
  "$case_dir/healthy-v4.json")
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
export PYTHONPATH="$release:$repo"

set +e
python3 -m Mallory.core.campaign --config "$case_dir/healthy-v4.json" --out "$output" >"$log" 2>&1
campaign_code=$?
set -e
printf '%s\n' "$campaign_code" >"${output}.exit.txt"
if [[ -f "$output/result.json" ]]; then
  python3 -m Mallory.core.audit --campaign "$output" \
    --out "$output/offline-causal-audit.json" >>"$log" 2>&1 || true
fi
exit "$campaign_code"
