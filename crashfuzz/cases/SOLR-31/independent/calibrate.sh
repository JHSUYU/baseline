#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 run.py calibration/watch-exists \
  --agent solrforce-independent-agent.jar \
  --fault-plan calibration/fault.properties \
  > calibration/watch-exists-driver.log 2>&1
