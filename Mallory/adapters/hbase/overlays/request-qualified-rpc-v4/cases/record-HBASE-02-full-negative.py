#!/usr/bin/env python3
"""Pin an offhost HBASE-02 negative campaign without copying its raw traces."""

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256(path):
    return sha256_bytes(path.read_bytes())


def check(ok, reason):
    if not ok:
        raise ValueError(reason)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    archive = args.archive.resolve()
    summary = json.loads((campaign / "result.json").read_text())
    audit = json.loads((campaign / "offline-causal-audit.json").read_text())
    check(summary["case_id"] == "HBASE-02" and summary["status"] == "queue_exhausted",
          "unexpected terminal campaign")
    check(summary["fault_trials_completed"] == 6 and
          summary["exact_exception_trials"] == 0 and
          summary["strict_target_trials"] == 0, "unexpected full trial counts")
    check(audit["report_gate_passed"] is True and
          audit["campaign_result_sha256"] == sha256(campaign / "result.json") and
          audit["target_retained_fault_trials"] == 0 and
          audit["archive_integrity_valid"] is True,
          "terminal audit or result binding failed")
    manifest = {str(p.relative_to(campaign)): sha256(p)
                for p in sorted(campaign.rglob("*")) if p.is_file()
                and p.name != ".campaign.lock"}
    archived = {}
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            if member.isdir():
                continue
            prefix = campaign.name + "/"
            check(member.isfile() and member.name.startswith(prefix) and
                  ".." not in Path(member.name).parts, "unsafe archive member")
            relative = member.name[len(prefix):]
            member_stream = stream.extractfile(member)
            check(member_stream is not None, "missing archive member stream")
            archived[relative] = sha256_bytes(member_stream.read())
    check(archived == manifest, "archive members differ from terminal raw files")
    rows = []
    for trial in summary["trials"]:
        if trial["trial_id"] == 0:
            continue
        trial_dir = campaign / "trials" / ("r%04d" % trial["trial_id"])
        result = json.loads((trial_dir / "result.json").read_text())
        feedback = result["feedback"]
        rows.append({"trial_id": trial["trial_id"],
                     "duration_seconds": trial["duration_seconds"],
                     "feedback_status": feedback["status"],
                     "all_faults_effective": feedback["all_faults_effective"],
                     "exact_target_branch_coverage_present": any(
                         "ConnectionImplementation#relocateRegion" in item and
                         "@910:branch:" in item for item in feedback["coverage_ids"]),
                     "strict_postfault_followups": len(
                         feedback["qualified_request_followups"]),
                     "target_exception_candidate": feedback["target_exception_candidate"],
                     "result_sha256": manifest[str((trial_dir / "result.json").relative_to(campaign))],
                     "raw_gzip_sha256": manifest[str((trial_dir / "events.jsonl.gz").relative_to(campaign))]})
    receipt = {
        "schema_version": 1, "case_id": "HBASE-02", "campaign": "request-token-scoped-v4-full",
        "classification": "precision_unverified_no_strict_fault_to_target_path",
        "not_high_quality_complete": True, "new_bug": False,
        "terminal_status": summary["status"], "duration_seconds": summary["duration_seconds"],
        "fault_trials_completed": summary["fault_trials_completed"],
        "strict_injected_trials": summary["strict_injected_trials"],
        "strict_target_trials": summary["strict_target_trials"],
        "exact_exception_trials": summary["exact_exception_trials"],
        "archive_host": "node1", "archive_path": str(archive),
        "archive_sha256": sha256(archive), "archive_bytes": archive.stat().st_size,
        "campaign_path": str(campaign), "result_sha256": manifest["result.json"],
        "audit_sha256": manifest["offline-causal-audit.json"],
        "config_sha256": manifest["config.json"],
        "file_sha256": manifest, "trials": rows,
        "source_limitation": "The existing MiniCluster test creates an enabled table; this fault schedule did not establish a disabled table-state view, so absence of TableNotEnabledException is limited to this workload.",
    }
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print("PASS HBASE-02 offhost archive/negative receipt", len(manifest), "files")


if __name__ == "__main__":
    main()
