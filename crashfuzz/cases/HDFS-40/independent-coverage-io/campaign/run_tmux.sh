#!/usr/bin/env bash
set -euo pipefail
cd /users/ZhenyuLi/baseline
exec python3 crashfuzz/cases/HDFS-40/independent-coverage-io/campaign/run_campaign.py >> crashfuzz/cases/HDFS-40/independent-coverage-io/campaign/driver.log 2>&1
