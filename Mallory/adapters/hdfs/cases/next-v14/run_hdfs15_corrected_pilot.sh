#!/usr/bin/env bash
set -euo pipefail
mkdir -p /tmp/mallory-lanes
cd /tmp
export PYTHONPATH=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf:/users/ZhenyuLi/baseline
exec flock -x /tmp/mallory-lanes/hdfs-lane1.lock python3 -m Mallory.core.campaign --config /users/ZhenyuLi/baseline/Mallory/adapters/hdfs/cases/next-v14/HDFS-15-corrected-nn-pilot.json --out /users/ZhenyuLi/baseline/data/mallory/pilots_v14/HDFS-15-corrected-nn
