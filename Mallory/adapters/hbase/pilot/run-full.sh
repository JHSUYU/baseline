#!/usr/bin/env bash
set -euo pipefail

runtime=/users/ZhenyuLi/.mallory-worktrees/hbase/runtime
export PYTHONPATH="$runtime/python"
exec python3 -m Mallory.core.campaign \
  --config "$runtime/cases/HBASE-01/full.json" \
  --out /users/ZhenyuLi/.mallory-worktrees/hbase/full-HBASE-01
