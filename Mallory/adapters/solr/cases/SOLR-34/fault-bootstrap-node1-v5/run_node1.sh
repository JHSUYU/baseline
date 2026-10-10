#!/usr/bin/env bash
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$case_dir/run_campaign.py" --mode bounded_fault_bootstrap \
  --admission-receipt "$case_dir/admission-bootstrap-node1.json"
