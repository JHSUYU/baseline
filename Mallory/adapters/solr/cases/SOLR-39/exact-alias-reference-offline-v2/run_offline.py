#!/usr/bin/env python3
"""Reaudit the immutable SOLR-39 healthy archive without starting a JVM."""

from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
from pathlib import Path

from audit_identity import PREFIX, audit_rows

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
ARCHIVE = ROOT / "data/mallory/evidence_archives/SOLR-39-aliasref-healthy-node1-v1.tar.gz"
MANIFEST = ROOT / "data/mallory/evidence_archives/SOLR-39-aliasref-healthy-node1-v1.members.json"
ARCHIVE_SHA = "d84c06f6b10af3375c807aab723c3794c7ff66d2b58bfb177bf21ce1298106db"
PREFIX_IN_ARCHIVE = "SOLR-39-aliasref-healthy-node1-v1/"
MEMBERS = ("trials/r0000/events.jsonl.gz", "trials/r0000/junit.log",
           "trials/r0000/junit-receipt.json", "result.json")
OUTPUT = HERE / "evidence-review.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha(ARCHIVE.read_bytes()) != ARCHIVE_SHA:
        raise ValueError("sealed archive hash changed")
    contents = {}
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        for member in MEMBERS:
            stream = tar.extractfile(PREFIX_IN_ARCHIVE + member)
            if stream is None:
                raise ValueError(f"missing archive member {member}")
            data = stream.read()
            if sha(data) != manifest["files"][member]:
                raise ValueError(f"archive member hash changed: {member}")
            contents[member] = data
    receipt = json.loads(contents["trials/r0000/junit-receipt.json"])
    if receipt["tests"] != 1 or receipt["failures"] or receipt["errors"] or \
            receipt["status"] != "passed":
        raise ValueError("sealed healthy JUnit did not pass")
    events = [json.loads(line) for line in gzip.decompress(
        contents["trials/r0000/events.jsonl.gz"]).decode("utf-8").splitlines() if line]
    log = contents["trials/r0000/junit.log"].decode("utf-8", errors="replace")
    markers = [json.loads(line.split(PREFIX, 1)[1]) for line in log.splitlines() if PREFIX in line]
    audit = audit_rows(events, markers, log.count("MALLORY_ALIAS_REF_TRANSFORM_ERROR"))
    if audit["exact_target_checks"] != 4 or audit["paired_field_events"] != 310 or \
            len(audit["candidate_paths"]) != 1 or audit["transform_errors"]:
        raise ValueError("healthy path gate changed; review exact evidence")
    result = {
        "schema_version": 1,
        "case_id": "SOLR-39",
        "review_kind": "offline_exact_alias_reference_reaudit_of_sealed_healthy_run",
        "archive": str(ARCHIVE.relative_to(ROOT)),
        "archive_sha256": ARCHIVE_SHA,
        "member_sha256": {member: manifest["files"][member] for member in MEMBERS},
        "junit": {"tests": receipt["tests"], "failures": receipt["failures"],
                  "errors": receipt["errors"], "status": receipt["status"]},
        "audit": audit,
        "source_conclusion": (
            "The node2 watcher process getData door precedes setIfNewer publishing an "
            "Aliases reference to its volatile cache field. The same manager and exact "
            "reference are read in the routed request constructor and selected check, "
            "with no intervening publication. The field link is therefore qualified "
            "for a bounded fault pilot; fault-time target retention is still untested."),
        "fault_pilot_completed": False,
        "new_bug_confirmed": False,
    }
    OUTPUT.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case_id": result["case_id"], "paired_field_events": 310,
                      "qualified_healthy_paths": 1, "output": str(OUTPUT)}, sort_keys=True))


if __name__ == "__main__":
    main()
