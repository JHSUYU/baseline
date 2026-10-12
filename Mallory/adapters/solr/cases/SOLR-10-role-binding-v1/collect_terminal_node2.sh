#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-10-role-binding-v1"
out="$base/data/mallory/full_solr10_role_v1_node2/SOLR-10"
export_dir="$base/data/mallory/export_solr10_role_v1_node2/SOLR-10"
lock=/tmp/mallory-lanes/solr-routed-alias-v23.lock

mkdir -p "$(dirname "$export_dir")" "$(dirname "$lock")"
exec flock -n "$lock" python3 "$case_dir/collect_terminal.py" \
  --campaign "$out" --export "$export_dir"
