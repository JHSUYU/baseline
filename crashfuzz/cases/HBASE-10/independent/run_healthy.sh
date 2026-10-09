#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-10/independent
./run.sh run healthy > healthy.log 2>&1
status=$?
printf 'RUN_EXIT=%s\n' "$status" >> healthy.log
exit "$status"
