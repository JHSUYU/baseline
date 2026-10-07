#!/usr/bin/env python3
"""Verify archived original-JUnit trials and independently audit raw identity."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from audit_pilot_v3 import audit_trial, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.manifest.read_text())
    archive = args.manifest.parent / receipt["archive"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == receipt["archive_sha256"]
    content = {}
    with tarfile.open(archive, "r:gz") as tar:
        for item in receipt["files"]:
            path = Path(item["path"])
            assert not path.is_absolute() and ".." not in path.parts
            raw = tar.extractfile(item["path"]).read()
            assert len(raw) == item["bytes"]
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            content[item["path"]] = raw
    trials = []
    for number in range(receipt["first_trial"], receipt["last_trial"] + 1):
        directory = f"r{number:03d}"
        trial = json.loads(content[f"{directory}/trial.json"])
        manifest = json.loads(content[f"{directory}/manifest.json"])
        assert trial["number"] == number
        assert manifest["original_junit"] == receipt["original_junit"]
        assert manifest["original_source_commit"] == receipt["source_commit"]
        audited = audit_trial(trial, manifest, rows(content[f"{directory}/actor-events.tsv"]))
        audited["number"] = number
        if audited["strict_exact_actor"] != trial["strict_exact_actor"]:
            raise AssertionError(f"{directory}: strict mismatch")
        after = {e["seq"] for e in audited["same_core_guards_after_fault"]}
        joined = any(e["guard_seq"] in after and e["same_node"]
                     for e in audited["target_guard_sender_lineage"])
        if trial["effective"] != (trial["strict_exact_actor"] and joined):
            raise AssertionError(f"{directory}: effective budget mismatch")
        trials.append(audited)
    out = {"archive": receipt["archive"], "archive_sha256": receipt["archive_sha256"],
           "original_junit": receipt["original_junit"], "source_commit": receipt["source_commit"],
           "first_trial": receipt["first_trial"], "last_trial": receipt["last_trial"],
           "attempts": len(trials), "strict": sum(t["strict_exact_actor"] for t in trials),
           "effective": sum(t["ledger_effective"] for t in trials),
           "max_ordered_faults": max(t["planned_faults"] for t in trials),
           "target_exceptions": sum(t["ledger_target_exception"] for t in trials),
           "junit_failures": sum(t["junit_exit"] != 0 for t in trials),
           "elapsed_seconds": round(sum(t["elapsed_seconds"] for t in trials), 3),
           "target_actor_lineage_issues": sum(not e["same_node"] for t in trials
                                               for e in t["target_guard_sender_lineage"]),
           "strict_identity_issues": sum(len(t["issues"]) for t in trials
                                         if t["strict_exact_actor"]),
           "trials": trials}
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: out[key] for key in ("attempts", "strict", "effective",
                                                "target_exceptions", "junit_failures",
                                                "target_actor_lineage_issues",
                                                "strict_identity_issues", "max_ordered_faults",
                                                "elapsed_seconds")}))


if __name__ == "__main__":
    main()
