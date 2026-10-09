#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-22/independent
mkdir -p campaign
trials="${1:-80}"
faults="${2:-8}"
python3 fuzz.py --max-trials "$trials" --max-faults "$faults" >> campaign/driver.log 2>&1
code=$?
printf '%s\n' "$code" > campaign/driver.exit
exit "$code"
