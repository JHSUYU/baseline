#!/usr/bin/env python3
"""Hash-verify HDFS-30 HA raw evidence before removing regenerable exports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile


HERE = Path(__file__).resolve().parent
RAW = ("manifest.json", "runtime_trace.jsonl", "jacoco.exec", "junit.log",
       "driver.log")
DERIVED = ("covered_probes.txt", "covered_methods.txt",
           "covered_branch_counts.txt", "covered_lines.txt")
ROOT = ("ha-campaign-state.json", "ha-campaign-summary.json",
        "ha-trial-ledger.csv", "ha-campaign-driver.log",
        "ha-priority-change.json", "ha-provenance.json", "ha-final-audit.json",
        "README.md", "RecoveryProbe.java", "PatchRecovery.java",
        "CoverageRecovery.java", "RunOriginalJUnit.java", "run_original.py",
        "ha_campaign.py", "audit_ha_final.py", "archive_ha.py")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    state = json.loads((HERE / "ha-campaign-state.json").read_text())
    audit = json.loads((HERE / "ha-final-audit.json").read_text())
    if (state.get("active") is not None
            or state.get("stop_reason") not in (
                "attempt_budget_reached",
                "eight_valid_target_retaining_trials_without_feedback_gain",
                "queue_exhausted")
            or len(state["completed"]) != audit["completed_attempts"]):
        raise RuntimeError("HA campaign is not fully audited and stopped")
    archive = HERE / "ha-raw-evidence.tar.gz"
    receipt = HERE / "ha-raw-evidence-receipt.json"
    if archive.exists() or receipt.exists():
        raise RuntimeError("HA raw evidence has already been archived")
    folders = [HERE / name for name in
               ("healthy", "healthy-b", "healthy-node2", "healthy-active1-v2")]
    folders += [HERE / f"trial-{number:03d}"
                for number in range(1, len(state["completed"]) + 1)]
    paths = [HERE / name for name in ROOT if (HERE / name).is_file()]
    paths += sorted(HERE.glob("trial-*.plan.tsv"))
    paths += sorted(HERE.glob("trial-*-driver.log"))
    paths += sorted(HERE.glob("healthy*-driver.log"))
    for folder in folders:
        if not (folder / "manifest.json").is_file():
            raise RuntimeError("missing run manifest: " + str(folder))
        paths += [folder / name for name in RAW if (folder / name).is_file()]
    if len(paths) != len(set(paths)):
        raise RuntimeError("duplicate archive member")
    hashes = {str(path.relative_to(HERE)): sha(path.read_bytes()) for path in paths}
    temporary = archive.with_name(archive.name + ".tmp")
    with tarfile.open(temporary, "w:gz") as output:
        for path in paths:
            output.add(path, arcname=str(path.relative_to(HERE)), recursive=False)
    with tarfile.open(temporary, "r:gz") as verified:
        members = [member for member in verified if member.isfile()]
        if {member.name for member in members} != set(hashes):
            raise RuntimeError("HA archive member mismatch")
        for member in members:
            extracted = verified.extractfile(member)
            if extracted is None or sha(extracted.read()) != hashes[member.name]:
                raise RuntimeError("HA archive SHA-256 mismatch: " + member.name)
    temporary.replace(archive)
    removed = []
    for folder in folders:
        scratch = folder / "scratch"
        if scratch.exists():
            shutil.rmtree(scratch)
            removed.append(str(scratch.relative_to(HERE)))
        for name in DERIVED:
            derived = folder / name
            if derived.exists():
                derived.unlink()
                removed.append(str(derived.relative_to(HERE)))
    receipt.write_text(json.dumps({
        "archive": str(archive), "archive_sha256": sha(archive.read_bytes()),
        "completed_attempts": len(state["completed"]),
        "verified_entries": len(hashes), "raw_file_sha256": hashes,
        "raw_original_files_preserved": True,
        "removed_regenerable_paths": removed,
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_size_bytes": archive.stat().st_size,
                      "verified_entries": len(hashes),
                      "removed_regenerable_paths": len(removed)}, sort_keys=True))


if __name__ == "__main__":
    main()
