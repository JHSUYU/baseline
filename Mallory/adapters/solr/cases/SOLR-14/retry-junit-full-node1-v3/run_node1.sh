#!/usr/bin/env bash
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$case_dir/run_campaign.py" --mode full \
  --admission-receipt "$case_dir/admission-full-node1.json"
