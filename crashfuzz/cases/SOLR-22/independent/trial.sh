#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-22/independent
name="$1"
plan="$2"
python3 run.py "$name" --fault-plan "$plan" > "$name-driver.log" 2>&1
code=$?
printf '%s\n' "$code" > "$name.exit"
exit "$code"
