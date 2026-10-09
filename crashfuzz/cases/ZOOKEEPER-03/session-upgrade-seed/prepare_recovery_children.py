#!/usr/bin/env python3
"""Mutate only postfault I/O that a retained original-JUnit pilot actually exposed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "evidence/zk03-upgrade-pilot-raw.tar.gz"
OUT = HERE / "recovery-child-manifest.json"
EXPECTED_PARENTS = ("upgrade-pilot-001", "upgrade-pilot-002", "upgrade-pilot-010")


def main():
    with tarfile.open(ARCHIVE) as source:
        parent_audit = json.load(source.extractfile(
            "zk03-upgrade-pilot/pilot-feedback-audit.json"))
        parent_manifest = json.load(source.extractfile(
            "zk03-upgrade-pilot/pilot-manifest.json"))
        if parent_audit["status"] != "queue_exhausted" or \
                parent_audit["strict_injections"] != 10 or \
                parent_audit["target_retaining"] != 3 or \
                tuple(row["run_id"] for row in parent_audit["trials"]
                      if row["target_after_final_fault"]) != EXPECTED_PARENTS:
            raise RuntimeError("parent pilot identity or denominators changed")
        pilot_jobs = {job["pilot_id"]: job for job in parent_manifest["jobs"]}
        children = []
        for parent in EXPECTED_PARENTS:
            entry = next(row for row in parent_audit["trials"]
                         if row["run_id"] == parent)
            data = source.extractfile(
                f"zk03-upgrade-pilot/{parent}/events.tsv").read()
            if hashlib.sha256(data).hexdigest() != entry["events_sha256"]:
                raise RuntimeError("parent raw events SHA changed: " + parent)
            rows = [(int(x[0]), x[1], x[2:]) for x in
                    (line.split("\t") for line in data.decode().splitlines())]
            last_fault = max(seq for seq, kind, _ in rows if kind == "FAULT_APPLIED")
            target = entry["target_receipt"]["target_sequence"]
            if target <= last_fault:
                raise RuntimeError("no postfault parent target window")
            marker = ["write:1"] if parent == "upgrade-pilot-010" else \
                     ["read:1", "read:2", "write:1", "read:3", "read:5", "read:7"]
            for wanted in marker:
                op, ordinal = wanted.split(":")
                matches = [(seq, f) for seq, kind, f in rows
                           if last_fault < seq < target and kind == "IO"
                           and len(f) >= 7 and f[6] == "upgradedSession"
                           and f[1].startswith("client:" + (
                               "reconnected" if parent == "upgrade-pilot-010"
                               else "initial"))
                           and ":channel:2:op:" + op in f[2]
                           and f[3] == ordinal]
                if len(matches) != 1:
                    raise RuntimeError("new recovery I/O not unique in parent: " +
                                       parent + " " + wanted)
                seq, fields = matches[0]
                child = "@@".join(fields[:4])
                prefix = pilot_jobs[parent]["selector"]
                children.append({"child_id": f"recovery-child-{len(children)+1:03d}",
                                 "parent": parent, "plan": [prefix, child],
                                 "parent_new_io_sequence": seq,
                                 "parent_last_fault_sequence": last_fault,
                                 "parent_target_sequence": target,
                                 "child_family": ("reconnected" if parent.endswith("010")
                                                  else "initial") + ":" + op,
                                 "priority": 12 if parent.endswith("010") else
                                             10 if ordinal in ("1", "2") else 5,
                                 "fault_relations": ["same_session", "same_session"]})
    plans = [tuple(x["plan"]) for x in children]
    if len(plans) != 13 or len(set(plans)) != 13:
        raise RuntimeError("recovery-child queue not thirteen unique plans")
    result = {"case_id": "ZOOKEEPER-03", "phase": "session-upgrade-recovery-children",
              "original_junit": parent_manifest["original_junit"],
              "original_commit": parent_manifest["original_commit"],
              "check": parent_manifest["check"],
              "session_tag": "upgradedSession", "fault_type": "IOException",
              "max_trials": 13, "parent_pilot_archive_sha256": hashlib.sha256(
                  ARCHIVE.read_bytes()).hexdigest(),
              "parent_pilot_manifest_sha256": hashlib.sha256(
                  (HERE / "pilot-manifest.json").read_bytes()).hexdigest(),
              "agent_sha256": parent_manifest["agent_sha256"], "jobs": children}
    OUT.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"jobs": len(children), "manifest_sha256": hashlib.sha256(
        OUT.read_bytes()).hexdigest(), "parents": EXPECTED_PARENTS}, sort_keys=True))


if __name__ == "__main__":
    main()
