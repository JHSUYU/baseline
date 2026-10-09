#!/usr/bin/env python3
"""Verify a compressed copy of raw evidence, then drop regenerable exports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

import campaign


HERE = Path(__file__).resolve().parent
RAW_NAMES = ("manifest.json", "runtime_trace.jsonl", "jacoco.exec",
             "junit.log", "fault-plan.tsv", "driver.log")
STATE_NAMES = ("campaign-state.json", "coverage-correction.json",
               "pre-target-priority-change.json", "provenance.json",
               "ha-pilot-evidence.json", "final-audit.json")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    if (state.get("stop_reason") != "budget" or state.get("active") is not None
            or len(state["completed"]) != state["budget"]["max_trials"]):
        raise RuntimeError("campaign must finish its budget and have no active trial")
    archive = HERE / "raw-evidence.tar.gz"
    receipt = HERE / "raw-evidence-receipt.json"
    if archive.exists() or receipt.exists():
        raise RuntimeError("raw evidence already archived")
    completed = [Path(trial["run"]) for trial in state["completed"]]
    other = ([Path(path) for path in state["healthy_dirs"]]
             + [HERE / name for name in
                ("healthy-ha-failover-resources", "ha-smoke-file",
                 "ha-smoke-file-b")])
    directories = list(dict.fromkeys(completed + other))
    paths = [HERE / name for name in STATE_NAMES if (HERE / name).is_file()]
    for directory in directories:
        if not (directory / "manifest.json").is_file():
            raise RuntimeError("missing manifest: " + str(directory))
        paths.extend(directory / name for name in RAW_NAMES
                     if (directory / name).is_file())
    if len(paths) != len(set(paths)):
        raise RuntimeError("duplicate evidence path")
    hashes = {str(path.relative_to(HERE)): digest(path.read_bytes()) for path in paths}
    temporary = archive.with_name(archive.name + ".tmp")
    with tarfile.open(temporary, "w:gz") as output:
        for path in paths:
            output.add(path, arcname=str(path.relative_to(HERE)), recursive=False)
    with tarfile.open(temporary, "r:gz") as check:
        members = [member for member in check if member.isfile()]
        if {member.name for member in members} != set(hashes):
            raise RuntimeError("archive membership mismatch")
        for member in members:
            with check.extractfile(member) as stream:
                if digest(stream.read()) != hashes[member.name]:
                    raise RuntimeError("archive SHA-256 mismatch: " + member.name)
    temporary.replace(archive)
    removed = []
    for directory in completed:
        scratch = directory / "scratch"
        if scratch.exists():
            shutil.rmtree(scratch)
            removed.append(str(scratch.relative_to(HERE)))
        for category in ("probes", "methods", "branch_counts", "lines"):
            export = directory / ("covered_" + category + ".txt")
            if export.exists():
                export.unlink()
                removed.append(str(export.relative_to(HERE)))
    campaign.atomic_json(receipt, {
        "completed_trials": len(completed),
        "archive": str(archive), "archive_sha256": digest(archive.read_bytes()),
        "raw_file_sha256": hashes, "verified_entry_count": len(hashes),
        "raw_original_files_preserved": True,
        "removed_regenerable_paths": removed,
    })
    print(json.dumps({"archive_size_bytes": archive.stat().st_size,
                      "verified_entries": len(hashes),
                      "removed_regenerable_paths": len(removed)}, sort_keys=True))


if __name__ == "__main__":
    main()
