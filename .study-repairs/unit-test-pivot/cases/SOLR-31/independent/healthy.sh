#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 run.py healthy-01 > healthy-01-driver.log 2>&1
