#!/usr/bin/env python3
"""Select the released fallback JUnit method for the shared ASM/JaCoCo runner."""
from pathlib import Path
import subprocess
import sys

RUNNER = Path(__file__).resolve().parent.parent / "run_original.py"
raise SystemExit(subprocess.call([sys.executable, str(RUNNER),
                                  "--test-method", "testLeaseRecoveryAfterFailover",
                                  *sys.argv[1:]]))
