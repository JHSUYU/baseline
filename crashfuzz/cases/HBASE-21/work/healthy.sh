#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-21/work
bash run.sh run healthy > logs/healthy.log 2>&1
status=$?
printf '%s\n' "$status" > logs/healthy.exit
exit "$status"
