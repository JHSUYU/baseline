"""A domain checker separate from the check-site observation."""

import os
from pathlib import Path
import sys


answer = (Path(os.environ["ADHOCFUZZ_RUN_DIR"]) /
          "workload-result.txt").read_text(encoding="utf-8").strip()
print(answer)
sys.exit(0 if answer == "OK" else 1)
