#!/usr/bin/env bash
set -euo pipefail
cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-34/actor-v2
test "$(hostname)" = node2.baseline.silentfailure-pg0.utah.cloudlab.us
test -f node2-health-audit.json
trap 'status=$?; printf "%s\n" "$status" > campaign/node2-run-80.exit' EXIT
python3 fuzz_v2.py --max-trials 80 --max-faults 8
