#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 run.py healthy-03 --agent solrforce-independent-agent.jar > healthy-03-driver.log 2>&1
