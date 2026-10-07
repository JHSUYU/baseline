#!/usr/bin/env python3
"""Reclaim only completed case-local MiniDFSCluster scratch trees."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent.parent.parent
ALLOWED = ("HDFS-37",)


def size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=ALLOWED, required=True)
    args = parser.parse_args()
    evidence = BASE / args.case / "independent/evidence"
    runs = evidence / "runs"
    removed = 0
    bytes_removed = 0
    if runs.is_dir():
        for scratch in runs.glob("*/attempt-*/scratch"):
            # A manifest is written only after the JUnit and coverage reader
            # have exited. Never touch an active trial without its manifest.
            if scratch.is_dir() and (scratch.parent / "manifest.json").is_file():
                bytes_removed += size(scratch)
                shutil.rmtree(scratch)
                removed += 1
    healthy = evidence / "healthy"
    scratch = healthy / "scratch"
    if scratch.is_dir() and (healthy / "manifest.json").is_file():
        bytes_removed += size(scratch)
        shutil.rmtree(scratch)
        removed += 1
    print(f"{args.case}: removed {removed} completed scratch trees, {bytes_removed} bytes")


if __name__ == "__main__":
    main()
