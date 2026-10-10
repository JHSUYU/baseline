#!/usr/bin/env bash
set -euo pipefail
mode="${1:?healthy or full}"
case_dir="$(cd "$(dirname "$0")" && pwd)"
lock_root=/tmp/mallory-lanes
mkdir -p "$lock_root"
exec 8>"$lock_root/solr-source-graphchecker-8.11.4.lock"
exec 9>"$lock_root/solr-node2-lane3.lock"
flock -n 8
flock -n 9
exec python3 "$case_dir/run_campaign.py" --mode "$mode" --admission-receipt "$case_dir/admission-${mode}-node2.json"
