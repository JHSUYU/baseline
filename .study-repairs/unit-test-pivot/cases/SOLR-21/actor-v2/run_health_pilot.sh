#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
trap 'printf "exit_code=%s\n" "$?" > health-pilot.exit' EXIT
date -u '+start_utc=%Y-%m-%d %H:%M:%S UTC'
python3 build_agent.py
python3 build_junit.py
python3 smoke_transform.py
python3 smoke_actor_match.py
python3 run_healthy.py
python3 calibrate.py
date -u '+end_utc=%Y-%m-%d %H:%M:%S UTC'
