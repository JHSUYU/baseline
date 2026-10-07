#!/usr/bin/env python3
"""Reproduce the HDFS31 V3/V4 boundary proof from frozen raw traces."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import audit_checkpoint
import campaign


OLD_PREUUID = (
    "535ec888f9d97608d01c",
    "d877cce0ebaf8909bfc2",
    "f1e1d3c9207d03f7ca57",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("anchor", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    anchor = args.anchor.resolve()
    state = json.loads((anchor / "campaign-state.json").read_text())
    manifest_path = anchor / "legacy21-freeze.manifest.json"
    frozen = json.loads(manifest_path.read_text())
    mirror = json.loads((anchor / "legacy21-node1-verified.json").read_text())
    migration = state.get("identity_rule_migration", {})
    errors = []
    if (migration.get("boundary_completed") != 21
            or migration.get("old_state_sha256") != frozen["checkpoint_sha256"]
            or state["completion_order"][:21] != frozen["completed_ids"]
            or sum(state["completed"][x]["result"]["valid_for_feedback"]
                   for x in state["completion_order"][:21]) != 16):
        errors.append("legacy boundary or denominator changed")
    if (mirror["archive_sha256"] != frozen["archive_sha256"]
            or mirror["manifest_sha256"] != sha(manifest_path)
            or mirror["verified_files"] != len(frozen["files"])):
        errors.append("cross-host raw receipt mismatch")
    if sha(anchor / "legacy21-freeze.tar.zst") != frozen["archive_sha256"]:
        errors.append("frozen archive SHA mismatch")
    bad_files = [item["path"] for item in frozen["files"]
                 if item["path"] != "campaign-state.json"
                 and (not (anchor / item["path"]).is_file()
                      or (anchor / item["path"]).stat().st_size != item["bytes"]
                      or sha(anchor / item["path"]) != item["sha256"])]
    frozen_state = subprocess.check_output(
        ["tar", "--zstd", "-xOf", str(anchor / "legacy21-freeze.tar.zst"),
         "campaign-state.json"])
    if hashlib.sha256(frozen_state).hexdigest() != frozen["checkpoint_sha256"]:
        bad_files.append("campaign-state.json@frozen-archive")
    if bad_files:
        errors.append(f"frozen raw SHA mismatch: {bad_files}")
    cases = []
    for ident in OLD_PREUUID:
        trace = audit_checkpoint.rows(anchor / "runs" / ident / "attempt-1" / "runtime_trace.jsonl")
        fault = next(row for row in trace if row["event"] == "FAULT_APPLIED")
        later = [row for row in trace if row["event"] == "DIRECT_TARGET_CHECK"
                 and row["seq"] > fault["seq"] and row["actorKey"] == fault["actorKey"]]
        if len(later) != 1:
            errors.append(f"{ident}: expected one postfault selected target")
            continue
        target = later[0]
        old_checks = campaign.postfault(trace, [fault], True, "legacy-v3")[0]
        new_checks = campaign.postfault(trace, [fault], True, "actor-continuity-v4")[0]
        if len(old_checks) != 0 or len(new_checks) != 1:
            errors.append(f"{ident}: V3/V4 target count differs")
        controls = {}
        for same_uuid in (False, True):
            candidate_fault = copy.deepcopy(fault)
            if same_uuid:
                candidate_fault["dnUuidRaw"] = target["dnUuidRaw"]
            for dimension, field in (("episode", "startupEpisode"),
                                     ("object", "dnObjectId"),
                                     ("service", "serviceObjectId")):
                candidate_target = copy.deepcopy(target)
                candidate_target[field] = 999999
                key = ("same_uuid_" if same_uuid else "raw_") + dimension
                a = campaign.actor_lineage_proof(trace, candidate_fault, candidate_target)
                b = audit_checkpoint.actor_lineage_continuity(
                    trace, candidate_fault, candidate_target)
                controls[key] = {"controller": a, "independent_audit": b}
                if a or b:
                    errors.append(f"{ident}: {key} was wrongly accepted")
            candidate_fault["endpointRaw"] = "localhost/127.0.0.1:1"
            candidate_fault["actorNamenodeRaw"] = candidate_fault["endpointRaw"]
            key = ("same_uuid_" if same_uuid else "raw_") + "endpoint"
            a = campaign.actor_lineage_proof(trace, candidate_fault, target)
            b = audit_checkpoint.actor_lineage_continuity(trace, candidate_fault, target)
            controls[key] = {"controller": a, "independent_audit": b}
            if a or b:
                errors.append(f"{ident}: {key} was wrongly accepted")
        cases.append({"plan_id": ident, "fault_seq": fault["seq"],
                      "postfault_target_seq": target["seq"],
                      "actor_key": fault["actorKey"],
                      "dn_object_id": fault["dnObjectId"],
                      "service_object_id": fault["serviceObjectId"],
                      "namenode_endpoint_raw": fault["endpointRaw"],
                      "fault_uuid_raw": fault["dnUuidRaw"],
                      "target_uuid_raw": target["dnUuidRaw"],
                      "legacy_v3_targets_credited": len(old_checks),
                      "hypothetical_v4_targets": len(new_checks),
                      "negative_controls": controls})
    report = {"schema": "hdfs31-actor-continuity-v4-offline-audit-1",
              "pass": not errors, "issues": errors,
              "frozen_raw_files_sha_verified": len(frozen["files"]) - len(bad_files),
              "frozen_archive_sha256": frozen["archive_sha256"],
              "frozen_state_sha256": frozen["checkpoint_sha256"],
              "migration_state_sha256": sha(anchor / "campaign-state.json"),
              "legacy_completed": 21, "legacy_effective_unchanged": 16,
              "observations": cases}
    if args.output:
        campaign.save(args.output.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
