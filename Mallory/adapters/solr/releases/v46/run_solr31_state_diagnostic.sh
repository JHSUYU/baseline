#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
config="$base/Mallory/adapters/solr/cases/SOLR-31/config-v46p-lane4-state-watch-diagnostic.json"
runner="$base/Mallory/adapters/solr/releases/v46/run_solr31_state_diagnostic.py"
out="$base/data/mallory/diagnostic_v46p_state_watch_lane4/SOLR-31"
lock=/tmp/mallory-lanes/solr-lane4.lock

test "$(sha256sum "$config" | cut -d ' ' -f1)" = 18a56a64ebd7d07b3b88d5aea1d746af7908ab4ea0260b3e4a441bce257f2bea
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lock")"
exec flock -n "$lock" env PYTHONPATH="$release:$base" \
  python3 "$runner" --config "$config" --out "$out"
