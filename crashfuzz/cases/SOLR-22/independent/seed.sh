#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-22/independent
name="${1:-healthy-1}"
python3 run.py "$name" > "$name-driver.log" 2>&1
code=$?
printf '%s\n' "$code" > "$name.exit"
exit "$code"
