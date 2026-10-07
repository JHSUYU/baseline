#!/usr/bin/env python3
"""Mirror the node1 case result atomically into node0's shared checklist."""
import json
import os
from pathlib import Path
import subprocess
import time

case = Path('/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-17')
result = case / 'result.json'
temporary = case / 'result.node1.tmp'
remote = ('ZhenyuLi@node1:/users/ZhenyuLi/baseline/.study-repairs/'
          'unit-test-pivot/cases/HBASE-17/result.json')
terminal = {'budget_complete_pending_source_review', 'budget_exhausted_attempt_cap',
            'budget_exhausted_wall_cap', 'queue_exhausted'}
while True:
    process = subprocess.run(['scp', '-q', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
                              '-o', 'IdentitiesOnly=yes', remote, str(temporary)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if process.returncode == 0:
        data = json.loads(temporary.read_text())
        os.replace(temporary, result)
        if data.get('status') in terminal:
            break
    time.sleep(20)
