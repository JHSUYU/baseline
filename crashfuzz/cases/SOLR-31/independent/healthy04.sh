#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 run.py healthy-04 --agent solrforce-independent-agent.jar > healthy-04-driver.log 2>&1
