#!/usr/bin/env bash
set -o pipefail
cd /users/ZhenyuLi/baseline
python3 -u crashfuzz/cases/ZOOKEEPER-10/independent/campaign.py \
  >> crashfuzz/cases/ZOOKEEPER-10/independent/campaign.log 2>&1
status=$?
printf '%s\n' "$status" > crashfuzz/cases/ZOOKEEPER-10/independent/campaign.exit
sleep 3600
