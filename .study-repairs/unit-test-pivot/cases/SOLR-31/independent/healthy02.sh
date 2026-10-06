#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 run.py healthy-02 --agent solrforce-independent-agent.jar > healthy-02-driver.log 2>&1
