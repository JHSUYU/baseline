#!/usr/bin/env bash
set -euo pipefail
case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-05
while tmux has-session -t solr05-campaign 2>/dev/null; do
  sleep 10
done
exec /usr/bin/python3 "$case_dir/probe/campaign.py"
