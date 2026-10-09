#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 run.py healthy-05 --agent solrforce-independent-agent.jar \
  --test-seed F0993D5343E20BA5 > healthy-05-driver.log 2>&1
