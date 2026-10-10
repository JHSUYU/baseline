#!/usr/bin/env bash
set -euo pipefail

task_base=/users/ZhenyuLi/baseline
task_script="$task_base/Mallory/adapters/hdfs/cases/hdfs12-key-update-full-v3/collect_hdfs12_node2_full.py"
cd "$task_base"
exec env PYTHONPATH="$task_base" python3 "$task_script"
