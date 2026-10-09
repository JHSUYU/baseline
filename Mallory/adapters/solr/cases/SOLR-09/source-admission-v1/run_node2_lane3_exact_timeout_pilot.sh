#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-09/source-admission-v1"
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$case_dir/pilot-node2-lane3.json"
plan="$case_dir/pilot-plan-node2-lane3.json"
runner="$case_dir/run_exact_timeout_pilot.py"
healthy_audit="$case_dir/healthy-audit-node2-lane3.json"
out="$base/data/mallory/pilot_solr09_first_wait_timeout_node2_lane3/SOLR-09"
lane_lock=/tmp/mallory-lanes/solr-lane3.lock
source_lock=/tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock

test "$(hostname -s)" = node2
test "$(sha256sum "$config" | cut -d ' ' -f1)" = bf6bbb788c1b022c2635fad9204d3170aa4de30c2129eeff7072db90a28d8c7f
test "$(sha256sum "$plan" | cut -d ' ' -f1)" = c1d931e836b4473b2cae42ea4e5b0bb62b1ead7a3ea76e7ed630dba6e46e18d8
test "$(sha256sum "$runner" | cut -d ' ' -f1)" = ed540d97fe19a11a6b5b023784a32466b02331e8c0e32d9215cc8a6d2d1527db
test "$(sha256sum "$healthy_audit" | cut -d ' ' -f1)" = 134fb65da3877fc3dc23065ffde4a99c506556789b0a3d741ace059f799e8dca
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lane_lock")"
exec 9>"$lane_lock"
flock -n 9
exec 8>"$source_lock"
flock -n 8

# Five GiB floor, two one-GiB scratch allowances, and a 128 MiB sync margin.
disk_available=$(df -PB1 "$base" | awk 'NR == 2 { print $4 }')
test "$disk_available" -ge 7650410496
memory_available_kib=$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)
test "$memory_available_kib" -ge 8388608

python3 "$case_dir/preflight.py" --node2
exec env PYTHONPATH="$release:$base" python3 "$runner"
