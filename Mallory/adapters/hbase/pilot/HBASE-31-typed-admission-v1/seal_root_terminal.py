#!/usr/bin/env python3
"""Bind the completed original HBASE-31 raw archive to its current audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile


ROOT = Path("/users/ZhenyuLi/baseline")
CASE = ROOT / "data/mallory/cases/HBASE-31"
ARCHIVE = ROOT / "data/mallory/evidence_archives/campaign/HBASE-31.tar.gz"
MANIFEST = ARCHIVE.with_suffix(".manifest.json")
SEAL = ARCHIVE.with_name("HBASE-31.terminal-seal.json")
GAP = ROOT / "Mallory/adapters/hbase/pilot/HBASE-31-typed-admission-v1/predicate-source-gap.json"
PINS = {
    "config": "bf03aa144fea0072da9fca11519d751901259ff239d642f8984d5e77936831e7",
    "result": "68422ac12b13d017825fec023fee3ca3cea024a3d53e687e0891ea80e0c08a8f",
    "audit": "f7740a03a7f53e30d20f2ded63ce8ec2b79779ea815dd9c262a473196d3744c3",
    "archive": "2cb5c895eabc4e8ad3a30984d6929393259bab090cda0b279b293457606a9291",
    "manifest": "cf1f1d3ad26e5931fd73fb62bde7907852e58f07f6782cb8cdb911335ad24f66",
    "gap": "62c59d56f3adc259c97f500a21b50c2286d2553b22215295028e3118d1a3f074",
}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"SHA mismatch: {path}")


def main() -> None:
    for name, path in (("config", CASE / "config.json"),
                       ("result", CASE / "result.json"),
                       ("audit", CASE / "offline-causal-audit.json"),
                       ("archive", ARCHIVE), ("manifest", MANIFEST), ("gap", GAP)):
        check(path, PINS[name])
    config = json.loads((CASE / "config.json").read_text())
    result = json.loads((CASE / "result.json").read_text())
    audit = json.loads((CASE / "offline-causal-audit.json").read_text())
    manifest = json.loads(MANIFEST.read_text())
    if not (config["case_id"] == result["case_id"] == audit["case_id"] == "HBASE-31"
            and config["cluster_test"] == result["cluster_test"] ==
            "org.apache.hadoop.hbase.regionserver.TestRegionMove#testDisableAndMove"
            and config["target"]["throw_site"] ==
            "org.apache.hadoop.hbase.regionserver.RSRpcServices#throwOnWrongStartCode(J)V@2011:throw:1"
            and result["status"] == audit["terminal_status"] == "budget_exhausted"
            and result["fault_trials_completed"] == 80 and
            len(result["trials"]) == audit["trial_count"] == 81 and
            result["duration_seconds"] == 3112.009 and
            result["healthy_junit_validation"]["status"] == "passed" and
            result["healthy_junit_validation"]["tests"] == 1 and
            result["healthy_junit_validation"]["failures"] == 0 and
            result["healthy_junit_validation"]["errors"] == 0 and
            result["runtime_attestation"]["valid"] is True and
            result["runtime_attestation"]["observed_target_class_sha256"] ==
            config["expected_target_class_sha256"] and
            audit["campaign_result_sha256"] == PINS["result"] and
            audit["archive_integrity_valid"] is True and
            audit["report_gate_passed"] is True and
            manifest["source_result_sha256"] ==
            "722fc6efdf820da093d890c7a0aa0b519ce2d14070613dde782ac85ffc5df609"):
        raise RuntimeError("completed target, test, runtime, or audit identity differs")
    members: dict[str, str] = {}
    with tarfile.open(ARCHIVE, "r:gz") as packed:
        for member in packed:
            if (not member.isfile() or member.name in members or
                    member.name.startswith("campaigns/") or
                    ".." in Path(member.name).parts):
                raise RuntimeError("unsafe or duplicate archive member")
            data = packed.extractfile(member).read()
            members[member.name] = sha_bytes(data)
            source = CASE / member.name
            if not source.is_file():
                raise RuntimeError(f"raw member missing: {member.name}")
            if member.name != "result.json" and sha(source) != members[member.name]:
                raise RuntimeError(f"raw member differs: {member.name}")
        archived_result = json.loads(packed.extractfile("result.json").read())
    if sorted(members) != sorted(manifest["members"]):
        raise RuntimeError("archive manifest member set differs")
    scientific_result = dict(result)
    scientific_result.pop("evidence_archive", None)
    scientific_result.pop("dispatch_provenance", None)
    if scientific_result != archived_result:
        raise RuntimeError("archived scientific result differs from current result")
    if SEAL.exists():
        raise RuntimeError("terminal seal already exists")
    seal = {
        "schema_version": 1,
        "case_id": "HBASE-31",
        "kind": "original_full_terminal_archive_seal",
        "status": "budget_exhausted",
        "completed_fault_trials": 80,
        "duration_seconds": 3112.009,
        "healthy_junit": "1 passed, 0 failures, 0 errors",
        "selected_target_throws": result["exact_exception_trials"],
        "strict_injected_trials": result["strict_injected_trials"],
        "strict_target_trials": result["strict_target_trials"],
        "result_sha256": PINS["result"],
        "config_sha256": PINS["config"],
        "audit_sha256": PINS["audit"],
        "archive_sha256": PINS["archive"],
        "archive_manifest_sha256": PINS["manifest"],
        "source_gap_receipt_sha256": PINS["gap"],
        "archive_members_sha256": members,
        "archived_result_matches_current_after_removing_provenance_annotations": True,
        "audit_report_gate_passed": True,
        "supplemental_typed_v2_excluded_from_original_archive": True,
        "bug_claim": False,
    }
    SEAL.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"seal_sha256": sha(SEAL), "archive_members": len(members),
                      "result_sha256": PINS["result"], "audit_sha256": PINS["audit"]}))


if __name__ == "__main__":
    main()
