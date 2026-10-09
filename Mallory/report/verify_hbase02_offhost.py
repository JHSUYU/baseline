"""Verify the compact, losslessly archived HBASE-02 v4 terminal campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(data: Path) -> None:
    canonical = data / "cases/HBASE-02"
    compact = data / "HBASE-02/campaigns/request-token-scoped-v4-full-offhost"
    archive = data / "evidence_archives/campaign_request_token_scoped_v4/HBASE-02.tar.gz"
    index = json.loads((data / "quality_reviews/hbase02_v4_offhost/index.json").read_text())
    receipt_path = compact / "negative-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    expected = {
        "archive_sha256": archive,
        "receipt_sha256": receipt_path,
        "result_sha256": canonical / "result.json",
        "audit_sha256": canonical / "offline-causal-audit.json",
        "config_sha256": canonical / "config.json",
    }
    assert index["schema_version"] == 1 and index["case_id"] == "HBASE-02"
    assert index["classification"] == "faulted_path_unverified"
    assert index["archive_member_count"] == 60
    assert all(index[key] == digest(path.read_bytes()) for key, path in expected.items())
    assert receipt["schema_version"] == 1 and receipt["case_id"] == "HBASE-02"
    assert receipt["classification"] == "precision_unverified_no_strict_fault_to_target_path"
    assert receipt["archive_sha256"] == index["archive_sha256"]
    assert receipt["archive_bytes"] == archive.stat().st_size
    for name in ("result.json", "offline-causal-audit.json", "config.json"):
        assert (canonical / name).read_bytes() == (compact / name).read_bytes()
    result = json.loads((canonical / "result.json").read_text())
    audit = json.loads((canonical / "offline-causal-audit.json").read_text())
    assert result["case_id"] == audit["case_id"] == "HBASE-02"
    assert result["status"] == receipt["terminal_status"] == "queue_exhausted"
    assert result["healthy_seed_valid"] is True
    assert result["runtime_attestation"]["valid"] is True
    assert result["duration_seconds"] == receipt["duration_seconds"] == 222.729
    assert result["fault_trials_completed"] == receipt["fault_trials_completed"] == 6
    assert result["strict_injected_trials"] == receipt["strict_injected_trials"] == 5
    assert result["strict_target_trials"] == receipt["strict_target_trials"] == 0
    assert result["exact_exception_trials"] == receipt["exact_exception_trials"] == 0
    assert result["new_bug"] is None and receipt["new_bug"] is False
    assert audit["report_gate_passed"] is True
    assert audit["campaign_result_sha256"] == index["result_sha256"]
    assert audit["named_applied_faults"] == 5
    assert audit["target_retained_fault_trials"] == 0
    assert audit["unknown_applied_faults"] == 0
    assert audit["applied_fault_identity_valid"] is True
    assert audit["guidance_consistent"] is True
    assert audit["archive_integrity_valid"] is True
    assert len(audit["trials"]) == 7 and len(receipt["trials"]) == 6
    for number, row in enumerate(receipt["trials"], 1):
        trial = result["trials"][number]
        replay = audit["trials"][number]
        assert row["trial_id"] == trial["trial_id"] == number
        assert row["strict_postfault_followups"] == 0
        assert replay["qualified_request_followups"] == []
        assert replay["same_actor_target_after_fault"] is False
        assert trial["target_exception_candidate"] is False
        if number == 1:
            assert row["feedback_status"] == replay["recomputed_status"] == "fault_unmatched"
            assert trial["all_faults_effective"] is False
        else:
            assert row["feedback_status"] == replay["recomputed_status"] == "target_lost"
            assert trial["all_faults_effective"] is True
            assert replay["faults"][0]["applied_receipts"] == 1
            assert replay["faults"][0]["applied_identity_valid"] is True
    expected_members = receipt["file_sha256"]
    assert len(expected_members) == 60
    actual: dict[str, str] = {}
    prefix = "request-token-scoped-v4-full/"
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            if not member.isfile():
                continue
            assert member.name.startswith(prefix)
            relative = member.name.removeprefix(prefix)
            assert relative not in actual
            stream = bundle.extractfile(member)
            assert stream is not None
            content = stream.read()
            assert member.size == len(content)
            actual[relative] = digest(content)
            if relative in ("result.json", "offline-causal-audit.json", "config.json"):
                assert content == (canonical / relative).read_bytes()
    assert actual == expected_members
    for row in receipt["trials"]:
        number = row["trial_id"]
        assert row["result_sha256"] == actual[f"trials/r{number:04d}/result.json"]
        assert row["raw_gzip_sha256"] == actual[f"trials/r{number:04d}/events.jsonl.gz"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    verify(args.data_root)
    print("HBASE-02 compact offhost campaign: verified")
