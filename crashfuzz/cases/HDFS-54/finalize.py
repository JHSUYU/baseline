#!/usr/bin/env python3
"""Summarize a completed, checkpointed HDFS-54 campaign and archive raw evidence."""

import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
STATE = HERE / "campaign-state.json"
ARCHIVE = HERE / "evidence.tar.gz"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    state = json.loads(STATE.read_text())
    if state["status"] != "complete":
        raise SystemExit("campaign is not complete")
    trials = {row["id"]: row for row in state["trials"]}
    seed = trials["seed-original"]
    fixed = trials["fixed-control"]
    mutants = [row for row in state["trials"] if row["id"].startswith("mutation-")]
    confirmed = (seed["result"] == "known_bug_reproduced"
                 and fixed["result"] == "fix_control_recovered"
                 and len(seed["summary"]["runtime_dn_identities"]) == 3
                 and seed["summary"]["generic_stale_key_catches_after_fault"] >= 3)
    selected = []
    for row in state["trials"]:
        directory = HERE / "campaign-runs" / row["id"]
        for name in ("manifest.json", "junit.log", "runtime_trace.jsonl", "jacoco.exec",
                     "covered_probes.txt", "covered_methods.txt", "covered_branch_counts.txt",
                     "covered_lines.txt"):
            path = directory / name
            if path.is_file():
                selected.append(path)
    smoke = HERE / "runs" / "original-01"
    if (smoke / "manifest.json").is_file():
        for name in ("manifest.json", "junit.log", "runtime_trace.jsonl", "jacoco.exec"):
            path = smoke / name
            if path.is_file():
                selected.append(path)
    selected += sorted((HERE / "plans").glob("*.tsv"))
    with tarfile.open(ARCHIVE, "w:gz") as archive:
        for path in selected:
            archive.add(path, arcname=str(path.relative_to(HERE)))
    result = {
        "case_id": "HDFS-54", "bug_id": "HDFS-17897", "known_bug": True,
        "new_bug": False, "classification": (
            "known_bug_reproduced_only_in_adapted_control" if confirmed else "inconclusive"),
        "status": "quality_complete" if confirmed else "inconclusive",
        "bug_mark": "none",
        "unchanged_junit_generic_fuzz_detected_known_bug": False,
        "source_version": "Hadoop 3.4.3", "graph_used": False,
        "target_site": "FileChecksumHelper$StripedFileNonStripedChecksumComputer.checksumBlocks#L629",
        "source_path": "hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/apache/hadoop/hdfs/FileChecksumHelper.java",
        "function": "StripedFileNonStripedChecksumComputer.checksumBlocks()",
        "check_code": "if (!checksumBlockGroup(blockGroup)) throw new PathIOException(...)" ,
        "linked_upstream_check": "HDFS-11 BlockTokenSecretManager.retrieveDataEncryptionKey#L552",
        "original_junit_basis": "TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey",
        "workload_change": "XOR-2-1 striped file, 1 NameNode and 3 DataNodes",
        "fault": "real NameNode block-key rotation and expiry on all 3 DataNodes",
        "injected_io_faults": sum(row["summary"]["applied_faults"] for row in mutants),
        "fault_trials": len(mutants),
        "fully_applied_trials": sum(row["summary"]["applied_faults"] == 1
                                    for row in mutants),
        "target_after_fault": sum(
            row["summary"]["applied_faults"] == 1
            and row["summary"]["target_check_after_fault"] > 0 for row in mutants),
        "natural_key_expiry_target_after_fault": (
            seed["summary"]["target_false_after_fault"] > 0),
        "trial_count": len(state["trials"]),
        "injected_mutant_count": len(mutants),
        "target_retaining_mutant_count": sum(
            row["result"] == "target_retaining_fault_trial" for row in mutants),
        "elapsed_seconds": round(sum(row["summary"]["elapsed_seconds"]
                                     for row in state["trials"]), 3),
        "seed": seed["summary"], "fixed_control": fixed["summary"],
        "mutant_summaries": [{"id": row["id"], "result": row["result"],
                              "plan": row["plan"], "summary": row["summary"]}
                             for row in mutants],
        "pre_campaign_original_smoke": (
            {"manifest": "runs/original-01/manifest.json",
             "elapsed_seconds": json.loads((smoke / "manifest.json").read_text())["elapsed_seconds"],
             "runtime_trace": "runs/original-01/runtime_trace.jsonl"}
            if (smoke / "manifest.json").is_file() else None),
        "checkpoint": "campaign-state.json", "trial_ledger": "trial-ledger.csv",
        "evidence": {"checkpoint": "campaign-state.json",
                     "trial_ledger": "trial-ledger.csv",
                     "raw_archive": "evidence.tar.gz",
                     "seed_trace": "campaign-runs/seed-original/runtime_trace.jsonl",
                     "seed_log": "campaign-runs/seed-original/junit.log",
                     "fix_trace": "campaign-runs/fixed-control/runtime_trace.jsonl",
                     "fix_log": "campaign-runs/fixed-control/junit.log"},
        "evidence_archive": "evidence.tar.gz", "evidence_archive_sha256": sha(ARCHIVE),
        "evidence_archive_bytes": ARCHIVE.stat().st_size,
    }
    temp = HERE / "result.json.tmp"
    temp.write_text(json.dumps(result, indent=2) + "\n")
    temp.replace(HERE / "result.json")
    print(json.dumps({key: result[key] for key in
                      ("case_id", "classification", "trial_count", "elapsed_seconds",
                       "target_retaining_mutant_count", "evidence_archive_sha256")}))


if __name__ == "__main__":
    main()
