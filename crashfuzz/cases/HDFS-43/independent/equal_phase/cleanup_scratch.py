#!/usr/bin/env python3
"""Remove only completed supplementary HDFS-43 cluster scratch trees."""
from __future__ import annotations

from pathlib import Path
import shutil


def main() -> None:
    evidence = Path(__file__).resolve().parent / "evidence"
    removed = 0
    for scratch in (evidence / "runs").glob("*/attempt-*/scratch"):
        if scratch.is_dir() and (scratch.parent / "manifest.json").is_file():
            shutil.rmtree(scratch)
            removed += 1
    healthy = evidence / "healthy"
    scratch = healthy / "scratch"
    if scratch.is_dir() and (healthy / "manifest.json").is_file():
        shutil.rmtree(scratch)
        removed += 1
    print(f"HDFS-43 equal phase: removed {removed} completed scratch trees")


if __name__ == "__main__":
    main()
