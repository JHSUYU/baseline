#!/usr/bin/env bash
set -euo pipefail

task_base=/users/ZhenyuLi/baseline
task_script="$task_base/Mallory/adapters/hdfs/cases/hdfs26-retry-io-admission-v2/collect_hdfs26_node2_full.py"
cd "$task_base"
exec env PYTHONPATH="$task_base" python3 "$task_script"
