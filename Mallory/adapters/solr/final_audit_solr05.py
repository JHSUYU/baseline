#!/usr/bin/env python3
"""Audit the archived SOLR-05 campaign with the pinned final core release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


REPO = Path(__file__).resolve().parents[3]
ARCHIVE = REPO / "data/mallory/replays/SOLR-05-v4-junit"
RELEASE = REPO / ("Mallory/dispatch/releases/"
    "5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf")
INITIAL = ARCHIVE / "offline-causal-audit-initial.json"
PINNED = ARCHIVE / "offline-causal-audit-release-5820.json"
AUDIT_OUTPUT = REPO / "data/mallory/SOLR-05-v4-junit-release-5820.audit.json"
CANONICAL = ARCHIVE / "offline-causal-audit.json"
RECEIPT = ARCHIVE / "final-release-audit-receipt.json"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def archived() -> bool:
    result = ARCHIVE / "result.json"
    sync = ARCHIVE / "sync-receipt.json"
    if not all(path.is_file() for path in (result, sync, CANONICAL)):
        return False
    receipt = read(sync)
    initial = read(CANONICAL)
    expected = sha256(result)
    return (receipt.get("case_id") == "SOLR-05"
            and receipt.get("result_sha256") == expected
            and initial.get("case_id") == "SOLR-05"
            and initial.get("campaign_result_sha256") == expected)


def verify_release() -> dict:
    sys.path.insert(0, str(REPO))
    from Mallory.dispatch.core_release import verify
    manifest = verify(RELEASE / "manifest.json")
    if manifest["release_id"] != RELEASE.name:
        raise ValueError("core release identity differs")
    return manifest


def run_audit(manifest: dict) -> dict:
    if not INITIAL.is_file():
        shutil.copy2(CANONICAL, INITIAL)
    result_sha = sha256(ARCHIVE / "result.json")
    if read(INITIAL).get("campaign_result_sha256") != result_sha:
        raise ValueError("preserved initial audit does not bind the raw result")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(RELEASE) + os.pathsep + str(REPO)
    completed = subprocess.run(
        [sys.executable, "-m", "Mallory.core.audit", "--campaign", str(ARCHIVE),
         "--out", str(AUDIT_OUTPUT)], cwd="/tmp", env=environment, text=True,
        capture_output=True)
    if completed.returncode not in (0, 2) or not AUDIT_OUTPUT.is_file():
        raise RuntimeError("pinned audit failed: " + completed.stderr.strip()[:1000])
    audit = read(AUDIT_OUTPUT)
    if audit.get("campaign_result_sha256") != result_sha:
        raise ValueError("pinned audit does not bind the raw result")
    if audit.get("case_id") != "SOLR-05":
        raise ValueError("pinned audit has a different case ID")
    for name in ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py"):
        expected = manifest["files"]["Mallory/core/" + name]
        if audit.get("core_source_sha256", {}).get(name) != expected:
            raise ValueError("pinned audit used a different core source: " + name)
    shutil.copyfile(AUDIT_OUTPUT, PINNED)
    required = (audit.get("archive_integrity_valid") is True
                and audit.get("applied_fault_identity_valid") is True
                and audit.get("unknown_applied_faults") == 0
                and audit.get("target_claims_reverified") is True
                and audit.get("guidance_consistent") is True
                and audit.get("healthy_closure_proven") is True
                and isinstance(audit.get("healthy_observed_path_doors"), int)
                and not isinstance(audit.get("healthy_observed_path_doors"), bool)
                and audit["healthy_observed_path_doors"] > 0
                and audit.get("report_gate_passed") is True)
    temporary = CANONICAL.with_name(".offline-causal-audit.5820.tmp")
    shutil.copyfile(PINNED, temporary)
    os.replace(temporary, CANONICAL)
    receipt = {"schema_version": 1, "case_id": "SOLR-05",
               "result_sha256": result_sha, "core_release_id": RELEASE.name,
               "core_release_manifest_sha256": sha256(RELEASE / "manifest.json"),
               "initial_audit_sha256": sha256(INITIAL),
               "pinned_audit_sha256": sha256(PINNED),
               "canonical_audit_sha256": sha256(CANONICAL),
               "healthy_observed_path_doors": audit.get("healthy_observed_path_doors"),
               "named_applied_faults": audit.get("named_applied_faults"),
               "unknown_applied_faults": audit.get("unknown_applied_faults"),
               "guidance_consistent": audit.get("guidance_consistent"),
               "promotion_ready": required}
    pending = RECEIPT.with_name(".final-release-audit-receipt.tmp")
    pending.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(pending, RECEIPT)
    return receipt


def main() -> int:
    manifest = verify_release()
    while not archived():
        print("waiting for SHA-bound SOLR-05 terminal sync and initial audit", flush=True)
        time.sleep(30)
    receipt = run_audit(manifest)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    # A failing audit is still terminal evidence; promotion remains gated.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
