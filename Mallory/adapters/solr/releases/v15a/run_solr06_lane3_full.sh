#!/usr/bin/env bash
set -euo pipefail

baseline=/users/ZhenyuLi/baseline
release="$baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
config="$baseline/Mallory/adapters/solr/cases/SOLR-06/config-v15a-lane3-promoted-final.json"
output="$baseline/data/mallory/campaign_v15a_lane3/SOLR-06"
lock=/tmp/mallory-lanes/solr-lane3.lock

mkdir -p "$(dirname "$output")" "$(dirname "$lock")"
if [ -e "$output" ]; then
  echo "Refusing to reuse campaign output: $output" >&2
  exit 2
fi

cd "$baseline"
flock -n "$lock" env PYTHONPATH="$release:$baseline" \
  python3 -m Mallory.core.campaign --config "$config" --out "$output"
