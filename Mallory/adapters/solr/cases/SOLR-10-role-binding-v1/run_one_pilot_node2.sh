#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-10-role-binding-v1"
healthy="$base/data/mallory/calibration_solr10_role_v1_node2/SOLR-10"
plan="$healthy/role-plan-v1.json"
admission="$case_dir/admission-one-pilot-node2.json"
out="$base/data/mallory/pilot_solr10_role_v1_node2/SOLR-10"
lock=/tmp/mallory-lanes/solr-routed-alias-v23.lock

test -f "$admission"
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"

exec flock -n "$lock" python3 "$case_dir/run_one_pilot.py" \
  --config "$case_dir/config-role-v1-healthy-node2.json" \
  --plan "$plan" --admission-receipt "$admission" --output "$out"
