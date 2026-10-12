#!/usr/bin/env bash
set -euo pipefail

mode=${1:?pass healthy or full}
case "$mode" in healthy|full) ;; *) exit 2 ;; esac

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-14/full-v1"
lane_lock=/tmp/mallory-lanes/solr-lane3.lock
source_lock=/tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock
receipt="$case_dir/admission-$mode-node2.json"

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
