#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd -P)
cd "$here"
agent="$here/solrleadership-independent-agent.jar"

python3 run.py "$here/healthy-01" --agent "$agent" > "$here/healthy-01.driver.log" 2>&1
python3 audit_seed.py "$here/healthy-01" > "$here/healthy-01.audit.log" 2>&1
python3 run.py "$here/healthy-02" --agent "$agent" > "$here/healthy-02.driver.log" 2>&1
python3 audit_seed.py "$here/healthy-02" > "$here/healthy-02.audit.log" 2>&1
