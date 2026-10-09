#!/usr/bin/env bash
set -euo pipefail

lane_root=/users/ZhenyuLi/.mallory-worktrees/hbase/lane7
output_root="$lane_root/pilot-HBASE-16-recovery-v1-3"
config_path=/users/ZhenyuLi/baseline/Mallory/adapters/hbase/pilot/HBASE-16-lane7-recovery-v1-pilot3.json
release_root=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf

if [[ -e "$output_root" ]]; then
  echo "Refusing to reuse existing healthy output: $output_root" >&2
  exit 2
fi

exec 9>/tmp/mallory-lanes/hbase-lane7.lock
flock -n 9 || { echo 'HBase lane7 is busy' >&2; exit 3; }
mkdir -p "$output_root"
printf '%s\n' "$(date -u +%FT%TZ)" > "$output_root/worker-started-at.txt"

set +e
PYTHONPATH="$release_root:/users/ZhenyuLi/baseline" \
  python3 -m Mallory.core.campaign \
  --config "$config_path" --out "$output_root" \
  > "$output_root/worker.stdout.log" 2> "$output_root/worker.stderr.log"
status=$?
set -e
printf '%s\n' "$status" > "$output_root/worker-exit-code.txt"
printf '%s\n' "$(date -u +%FT%TZ)" > "$output_root/worker-finished-at.txt"
exit "$status"
