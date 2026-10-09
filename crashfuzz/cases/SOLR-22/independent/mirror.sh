#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-22/independent
python3 mirror.py >> mirror.log 2>&1
code=$?
printf '%s\n' "$code" > mirror.exit
exit "$code"
