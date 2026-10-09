#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-22/independent
method="${1:-testPullReplicaDisconnectsFromZooKeeper}"
output="supplemental/$method"
mkdir -p "$output"
python3 supplemental_smoke.py "$method" > "$output/driver.log" 2>&1
code=$?
printf '%s\n' "$code" > "$output/driver.exit"
exit "$code"
