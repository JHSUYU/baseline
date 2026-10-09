#!/usr/bin/env python3
"""Run unchanged and case-local instrumented original cluster JUnit seeds."""

from pathlib import Path
import subprocess
import sys


WORK = Path(__file__).resolve().parents[1]
RUN = WORK / "probe/run.py"


def main() -> None:
    for name, flags in (
        ("healthy-original", ["--original"]),
        ("healthy-instrumented", ["--coverage"]),
    ):
        output = WORK / "evidence" / name
        command = [sys.executable, str(RUN), str(output), *flags, "--timeout", "180"]
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
