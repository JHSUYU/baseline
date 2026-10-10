#!/usr/bin/env python3
"""Apply the proposed patch only in a temporary tree and run Python core tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATCH = Path(__file__).resolve().with_name("resource-identity.patch")
JAVA_FILES = (
    "Mallory/instrumentation/src/main/java/edu/uva/liftlab/mallory/instrumentation/FaultPlan.java",
    "Mallory/instrumentation/src/main/java/edu/uva/liftlab/mallory/instrumentation/Probe.java",
    "Mallory/instrumentation/src/test/java/edu/uva/liftlab/mallory/instrumentation/MalloryTransformerTest.java",
)


def main() -> None:
    subprocess.run(["git", "apply", "--check", str(PATCH)], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix="mallory-resource-identity-") as directory:
        staged = Path(directory)
        shutil.copytree(ROOT / "Mallory/core", staged / "Mallory/core",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in JAVA_FILES:
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        subprocess.run(["git", "apply", str(PATCH)], cwd=staged, check=True)
        subprocess.run([sys.executable, "-m", "unittest", "Mallory.core.test_core",
                        "Mallory.core.test_audit"], cwd=staged, check=True)
    print("Patch applies in isolation; Python core tests passed. Java/JVM not run.")


if __name__ == "__main__":
    main()
