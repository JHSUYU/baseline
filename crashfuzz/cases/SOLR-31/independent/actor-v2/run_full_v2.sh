#!/bin/bash
set -uo pipefail
cd /users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-31/independent/actor-v2
python3 -u campaign_v2.py --max-trials 80 --max-faults 8 --max-attempts 320 > full.log 2>&1
status=$?
printf '%s\n' "$status" > full.exit
exit "$status"
