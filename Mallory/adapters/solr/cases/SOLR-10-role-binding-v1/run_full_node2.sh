#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-10-role-binding-v1"
config="$case_dir/config-role-v1-full-node2.json"
admission="$case_dir/admission-full-node2.json"
out="$base/data/mallory/full_solr10_role_v1_node2/SOLR-10"
lock=/tmp/mallory-lanes/solr-routed-alias-v23.lock

test -f "$admission"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
exec flock -n "$lock" python3 "$case_dir/run_role_campaign.py" \
  --config "$config" --admission-receipt "$admission" --out "$out"
