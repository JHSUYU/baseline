#!/usr/bin/env bash
set -euo pipefail
mkdir -p /tmp/mallory-lanes
cd /tmp
export PYTHONPATH=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f:/users/ZhenyuLi/baseline
exec flock -x /tmp/mallory-lanes/hdfs-lane1.lock python3 /users/ZhenyuLi/baseline/Mallory/adapters/hdfs/run_focused_io_pilot.py --config /users/ZhenyuLi/baseline/Mallory/adapters/hdfs/cases/next-v25/HDFS-11-unique-error-response-pilot-v25.json --out /tmp/mallory-hdfs11-v25-unique-error-response-pilot --site hdfs:nn-get-data-encryption-key --max-doors 1 --core-release /users/ZhenyuLi/baseline/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f
