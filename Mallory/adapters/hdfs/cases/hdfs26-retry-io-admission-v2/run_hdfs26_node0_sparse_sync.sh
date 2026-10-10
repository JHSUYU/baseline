#!/usr/bin/env bash
set -euo pipefail

task_base=/users/ZhenyuLi/baseline
task_script="$task_base/Mallory/adapters/hdfs/cases/hdfs26-retry-io-admission-v2/sync_hdfs26_node0_sparse.py"
cd "$task_base"
exec python3 "$task_script"
