#!/usr/bin/env python3
"""Retain audit log and remove scratch only for checkpointed completed runs."""

import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def clean(directory):
    scratch = directory / "scratch"
    if not scratch.is_dir():
        return 0
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file() or not (directory / "junit.log").is_file():
        return 0
    manifest = json.loads(manifest_path.read_text())
    audit = scratch / "logs/hdfs-audit.log"
    if audit.is_file():
        shutil.copy2(audit, directory / "hdfs-audit.log")
    shutil.rmtree(scratch)
    manifest["scratch_cleanup"] = {
        "removed_after_checkpoint": True,
        "audit_log_retained": (directory / "hdfs-audit.log").is_file()}
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(manifest_path)
    return 1


def main():
    count = 0
    state = json.loads((HERE / "state.json").read_text())
    for row in state["trials"]:
        count += clean(HERE / "runs" / row["id"])
    prefix = HERE / "runtime-prefix"
    if (prefix / "state.json").is_file():
        state = json.loads((prefix / "state.json").read_text())
        for row in state["trials"]:
            count += clean(prefix / "runs" / row["id"])
        if state.get("fixed_replay"):
            count += clean(prefix / "fixed-replay" / state["fixed_replay"]["id"])
    print("completed_scratch_removed", count)


if __name__ == "__main__":
    main()
