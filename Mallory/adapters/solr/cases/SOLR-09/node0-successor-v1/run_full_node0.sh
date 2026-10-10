#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-09/node0-successor-v1"
config="$case_dir/config-full-node0.json"
admission="$case_dir/admission-full-node0.json"
out="$base/data/mallory/full_solr09_runtime_role_v1_node0/SOLR-09"
lane_lock=/tmp/mallory-lanes/solr-node0-v1.lock
source_lock=/tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock

test "$(hostname -s)" = node0
test -f "$admission"
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lane_lock")"
exec 9>"$lane_lock"
flock -n 9
exec 8>"$source_lock"
flock -n 8

disk_available=$(df -PB1 "$base" | awk 'NR == 2 { print $4 }')
test "$disk_available" -ge 6979321856
memory_available_kib=$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)
test "$memory_available_kib" -ge 8388608

exec python3 "$case_dir/run_campaign.py" --config "$config" \
  --admission-receipt "$admission" --out "$out"
