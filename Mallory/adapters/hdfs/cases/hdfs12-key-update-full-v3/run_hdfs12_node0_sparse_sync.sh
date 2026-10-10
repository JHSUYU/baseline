#!/usr/bin/env bash
set -euo pipefail

task_base=/users/ZhenyuLi/baseline
task_script="$task_base/Mallory/adapters/hdfs/cases/hdfs12-key-update-full-v3/sync_hdfs12_node0_sparse.py"
cd "$task_base"
exec python3 "$task_script"
