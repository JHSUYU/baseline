#!/usr/bin/env bash
set -euo pipefail

mode=${1:?pass healthy}
test "$mode" = healthy

base=/users/ZhenyuLi/baseline
case_id=$(basename "$(dirname "$(dirname "$(realpath "$0")")")")
case_dir="$base/Mallory/adapters/solr/cases/$case_id/healthy-state-watcher-v1"
receipt="$case_dir/admission-$mode-node2.json"
lane_lock=/tmp/mallory-lanes/$case_id-state-watcher.lock
source_lock=/tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock

test "$(hostname -s)" = node2
test -f "$receipt"
mkdir -p "$(dirname "$lane_lock")"
exec 9>"$lane_lock"
flock -n 9
exec 8>"$source_lock"
flock -n 8

disk_available=$(df -PB1 "$base" | awk 'NR == 2 { print $4 }')
test "$disk_available" -ge 7650410496
memory_available_kib=$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)
test "$memory_available_kib" -ge 8388608

exec python3 "$case_dir/run_campaign.py" --mode "$mode" \
  --admission-receipt "$receipt"
