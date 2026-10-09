#!/usr/bin/env python3
"""Prepare and advance one graph-free QJM original-JUnit fault campaign."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
CASES = HERE.parent / "cases"


def invoke(script: Path, *arguments: str) -> None:
    subprocess.run([sys.executable, str(script), *arguments], check=True)


def prepare(case: str) -> None:
    original = CASES / f"HDFS-{case}" / "independent" / "run_original.py"
    spec = importlib.util.spec_from_file_location(f"qjm_original_{case}", original)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {original}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build()

    overlay = HERE / "build" / f"HDFS-{case}" / "overlay" / "QjmRpcActor.class"
    if not overlay.is_file():
        invoke(HERE / "build_offline.py", case)

    root = HERE / "evidence" / f"HDFS-{case}"
    for seed in ("healthy-a", "healthy-b"):
        if not (root / seed / "manifest.json").is_file():
            invoke(HERE / "run_v2.py", "--case", case, "--name", seed)
    if not (root / "healthy-calibration.json").is_file():
        invoke(HERE / "calibrate_v2.py", "--case", case)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=("07", "09", "10"))
    parser.add_argument("--once", type=int, default=1,
                        help="number of new fault plans; zero only prepares healthy seeds")
    args = parser.parse_args()
    if args.once < 0:
        parser.error("--once must be nonnegative")
    prepare(args.case)
    invoke(HERE / "campaign_v2.py", "--case", args.case, "--once", str(args.once))


if __name__ == "__main__":
    main()
