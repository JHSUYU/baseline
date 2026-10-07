#!/usr/bin/env python3
"""Run two unchanged TestPread embedded-cluster healthy seeds for actor V2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parent
READ_MARKER = "FAULT:HDFS_DATA_TRANSFER:READ"
TARGET = "DFSInputStream.fetchBlockAt#L517-B5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(directory: Path) -> dict:
    manifest_path = directory / "manifest.json"
    trace_path = directory / "runtime_trace.jsonl"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("test") != "org.apache.hadoop.hdfs.TestPread#testPreadDFS":
        raise RuntimeError("wrong original JUnit: " + str(directory))
    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    checks = [row for row in rows if row.get("event") == "TARGET_CHECK"
              and row.get("siteId") == TARGET]
    reads = [row for row in rows if row.get("event") == "FAULT_POINT_OBSERVED"
             and row.get("marker") == READ_MARKER]
    bound = [row for row in reads if row.get("identityBound") is True]
    if manifest["returncode"] != 0 or not checks or not bound:
        raise RuntimeError("healthy JUnit/target/actor binding missing: " + str(directory))
    if any(row.get("event") == "TARGET_THROW" for row in rows):
        raise RuntimeError("healthy target threw: " + str(directory))
    return {"name": directory.name, "manifest_sha256": sha256(manifest_path),
            "trace_sha256": sha256(trace_path),
            "elapsed_seconds": manifest["elapsed_seconds"],
            "target_checks": len(checks), "data_reads": len(reads),
            "bound_data_reads": len(bound),
            "unbound_data_reads": len(reads) - len(bound),
            "raw_datanodes": len({row["actorUuid"] for row in bound}),
            "stable_read_selectors": sorted({
                (row["marker"], row["siteId"], row["actorKey"],
                 row["resourceKey"], row["hitOrdinal"]) for row in bound})}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="healthy-v2")
    args = parser.parse_args()
    summaries = []
    for name in (args.prefix + "-a", args.prefix + "-b"):
        directory = HERE / name
        if not (directory / "manifest.json").is_file():
            directory.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, str(HERE / "run_original.py"),
                       "--output", str(directory), "--timeout", "180"]
            with (directory / "driver.log").open("w") as output:
                finished = subprocess.run(command, stdout=output,
                                          stderr=subprocess.STDOUT, check=False)
            if finished.returncode:
                raise RuntimeError(f"healthy {name} runner exited {finished.returncode}")
        summary = inspect(directory)
        summaries.append(summary)
        print(json.dumps({key: value for key, value in summary.items()
                          if key != "stable_read_selectors"}), flush=True)
    common = set(map(tuple, summaries[0]["stable_read_selectors"])) & set(
        map(tuple, summaries[1]["stable_read_selectors"]))
    if not common:
        raise RuntimeError("no stable actor-bound read selector across healthy seeds")
    receipt = {"case_id": "HDFS-01", "generated_at_utc":
               datetime.now(timezone.utc).isoformat(),
               "original_junit": "org.apache.hadoop.hdfs.TestPread#testPreadDFS",
               "overlay_receipt_sha256": sha256(HERE / "build/receipt.json"),
               "seeds": summaries, "common_bound_read_selectors": len(common),
               "start_policy": "fresh MiniDFSCluster per seed; no fault"}
    path = HERE / (args.prefix + "-calibration.json")
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n")
    os.replace(temporary, path)
    print(json.dumps({"common_bound_read_selectors": len(common),
                      "receipt": str(path)}), flush=True)


if __name__ == "__main__":
    main()
