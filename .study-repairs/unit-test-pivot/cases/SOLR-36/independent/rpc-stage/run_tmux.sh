#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -u run_stages.py 2>&1 | tee -a campaign/stage.log
