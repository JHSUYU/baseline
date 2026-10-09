#!/usr/bin/env bash
set -euo pipefail
cd /users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-07/actor-v2
trap 'printf "%s\n" "$?" > clean-node2.exit' EXIT
hostname > clean-node2.host
date -u +'%Y-%m-%dT%H:%M:%SZ' > clean-node2.started
python3 run_v2.py clean-01 --clean
python3 run_v2.py clean-02 --clean
python3 - <<'PY'
import json
import re
from pathlib import Path

for name in ('clean-01', 'clean-02'):
    directory = Path(name)
    receipt = json.loads((directory / 'run.json').read_text())
    log = (directory / 'junit.log').read_text()
    if (receipt['exit_code'] != 0 or receipt['instrumented'] or
            receipt['agent_sha256'] is not None or receipt['plan'] is not None or
            not re.search(r'SOLR05_JUNIT_RESULT run=1 failures=0 ignored=0', log)):
        raise RuntimeError(f'original JUnit failed clean gate: {name}')
    print(name, receipt['elapsed_seconds'], 'original JUnit passed', flush=True)
PY
date -u +'%Y-%m-%dT%H:%M:%SZ' > clean-node2.finished
