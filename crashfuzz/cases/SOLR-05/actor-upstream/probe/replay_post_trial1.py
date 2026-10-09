#!/usr/bin/env python3
"""One independent original-JUnit replay of the first strict POST plan."""

import json
from pathlib import Path
import subprocess
import sys


CASE = Path(__file__).resolve().parents[1]
PLAN = json.loads((CASE / "evidence/campaign/state.json").read_text())["trials"][0]["plan"]
OUTPUT = CASE / "evidence/replay-post-001"
if OUTPUT.exists():
    raise SystemExit("Replay directory already exists; preserving prior raw evidence")
OUTPUT.mkdir(parents=True)
subprocess.run([sys.executable, str(CASE / "probe/run.py"), str(OUTPUT),
                "--coverage", "--faults", ";".join(PLAN), "--timeout", "360"],
               check=False)
subprocess.run([sys.executable, str(CASE / "probe/replay_audit.py"), str(OUTPUT)],
               check=True)
