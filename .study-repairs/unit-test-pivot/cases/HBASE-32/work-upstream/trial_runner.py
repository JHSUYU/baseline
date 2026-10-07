#!/usr/bin/env python3
"""Durable receipt for one isolated original-JUnit upstream fault trial."""

import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
trial_id, plan = sys.argv[1:]
steps = plan.split(";")
base_plan = ";".join(step for step in steps if step.startswith("RPC_FLUSH_REGION~"))
upstream_plan = ";".join(step for step in steps
                         if not step.startswith("RPC_FLUSH_REGION~"))
log = HERE / "logs" / (trial_id + ".log")
receipt = HERE / "logs" / (trial_id + ".exit")
if receipt.exists() or log.exists():
    raise SystemExit("Trial artifacts already exist: " + trial_id)
with log.open("w") as output:
    run = subprocess.run(["bash", str(HERE / "run.sh"), "run", trial_id,
                          base_plan, upstream_plan],
                         stdout=output, stderr=subprocess.STDOUT, check=False)
temp = receipt.with_suffix(".exit.tmp")
with temp.open("w") as output:
    output.write(str(run.returncode) + "\n")
    output.flush()
    os.fsync(output.fileno())
os.replace(temp, receipt)
