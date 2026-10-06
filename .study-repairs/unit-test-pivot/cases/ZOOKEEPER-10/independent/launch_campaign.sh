#!/usr/bin/env bash
set -o pipefail
cd /users/ZhenyuLi/baseline
python3 -u .study-repairs/unit-test-pivot/cases/ZOOKEEPER-10/independent/campaign.py \
  >> .study-repairs/unit-test-pivot/cases/ZOOKEEPER-10/independent/campaign.log 2>&1
status=$?
printf '%s\n' "$status" > .study-repairs/unit-test-pivot/cases/ZOOKEEPER-10/independent/campaign.exit
sleep 3600
