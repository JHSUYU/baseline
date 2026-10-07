#!/bin/bash
set -uo pipefail
cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-31/independent/actor-v2
python3 -u campaign_v2.py --max-trials 128 --max-faults 10 --max-attempts 512 > extension.log 2>&1
status=$?
printf '%s\n' "$status" > extension.exit
exit "$status"
