"""Verify a SHA-bound, audited predecessor produced outside a lane scheduler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collect import sha256
from .core_release import verify as verify_core_release


def verify(receipt_path: Path, release_manifest: Path) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != 1 or receipt.get("case_id") is None:
        raise ValueError("invalid external predecessor receipt")
    release = verify_core_release(release_manifest)
    if receipt.get("core_release_id") != release["release_id"]:
        raise ValueError("predecessor audit uses a different core release")
    root = receipt_path.parent
    result_path = root / "result.json"
    audit_path = root / "offline-causal-audit.json"
    if (sha256(result_path) != receipt.get("result_sha256")
            or sha256(audit_path) != receipt.get("audit_sha256")):
        raise ValueError("external predecessor evidence hash mismatch")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    case_id = receipt["case_id"]
    if (result.get("case_id") != case_id or audit.get("case_id") != case_id
            or result.get("status") not in ("budget_exhausted", "queue_exhausted")
            or result.get("fault_trials_completed", 0) <= 0
            or audit.get("campaign_result_sha256") != receipt["result_sha256"]
            or audit.get("terminal_status") != result.get("status")
            or audit.get("report_gate_passed") is not True
            or audit.get("healthy_closure_proven") is not True
            or not isinstance(audit.get("healthy_observed_path_doors"), int)
            or audit["healthy_observed_path_doors"] <= 0):
        raise ValueError("external predecessor is not an audited terminal campaign")
    expected = {name: release["files"][f"Mallory/core/{name}"]
                for name in ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")}
    if audit.get("core_source_sha256") != expected:
        raise ValueError("predecessor audit core hashes differ from release")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--core-release-manifest", type=Path, required=True)
    args = parser.parse_args()
    verified = verify(args.receipt, args.core_release_manifest)
    print(json.dumps({"predecessor_verified": verified["case_id"],
                      "result_sha256": verified["result_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
