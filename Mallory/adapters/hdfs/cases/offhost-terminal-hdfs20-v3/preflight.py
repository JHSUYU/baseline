#!/usr/bin/env python3
"""Read-only collector pins and case/output uniqueness check."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/offhost-terminal-hdfs20-v3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("HDFS-20", "HDFS-29", "HDFS-30"))
    args = parser.parse_args()
    manifest = json.loads((HERE / "cases.json").read_text())
    if (manifest.get("schema_version") != 1 or manifest.get("owner_host") != "node2" or
            manifest.get("core_release_manifest_sha256") !=
            sha(Path(manifest["core_release"]) / "manifest.json")):
        raise RuntimeError("offhost collector release pin changed")
    outputs = [row["source_output"] for row in manifest["cases"].values()]
    if len(set(outputs)) != len(outputs):
        raise RuntimeError("two cases share one source output")
    for case, row in manifest["cases"].items():
        if args.case is not None and case != args.case:
            continue
        config = Path(row["config_path"])
        if not config.is_file() or sha(config) != row["config_sha256"]:
            raise RuntimeError(f"missing or changed {case} campaign config")
        parsed = json.loads(config.read_text())
        budget = parsed["budget"]
        if (parsed.get("case_id") != case or
                (budget["trials"], budget["seconds"], budget["max_faults_per_trial"]) !=
                (80, 3600, 3) or
                parsed.get("calibration_only") is not False):
            raise RuntimeError(f"{case} is not the pinned full budget")
        for key in ("node2_state_root", "node0_state_root"):
            if not row[key].startswith(str(BASE / "data/mallory/dispatch/")):
                raise RuntimeError(f"{case} state root escapes dispatch")
        if not row["source_output"].startswith("/tmp/mallory-hdfs"):
            raise RuntimeError(f"{case} source output is not isolated")
    print(json.dumps({"status": "collector_preflight_pass", "case_id": args.case or "all",
                      "manifest_sha256": sha(HERE / "cases.json"),
                      "jvm_started": False}, sort_keys=True))


if __name__ == "__main__":
    main()
