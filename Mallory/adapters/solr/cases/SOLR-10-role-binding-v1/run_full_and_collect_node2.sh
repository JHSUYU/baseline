#!/usr/bin/env bash
set -u -o pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-10-role-binding-v1"
log_dir="$base/data/mallory"
mkdir -p "$log_dir"

bash "$case_dir/run_full_node2.sh" > "$log_dir/solr10-role-v1-full-node2.log" 2>&1
run_status=$?
printf 'campaign_exit=%s\n' "$run_status" >> "$log_dir/solr10-role-v1-full-node2.log"

bash "$case_dir/collect_terminal_node2.sh" > "$log_dir/solr10-role-v1-collector-node2.log" 2>&1
collect_status=$?
printf 'collector_exit=%s\n' "$collect_status" >> "$log_dir/solr10-role-v1-collector-node2.log"

if [ "$run_status" -ne 0 ]; then
  exit "$run_status"
fi
exit "$collect_status"
