"""Verify the archived HBASE-12 lane8 campaign and its limited oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify(data: Path, baseline: Path) -> None:
    canonical = data / "cases/HBASE-12"
    owned = baseline / "Mallory/adapters/hbase/pilot/HBASE-12-lane8-legacy-preservation-v1"
    archive = data / "evidence_archives/campaign_legacy_lane8/HBASE-12.tar.gz"
    index = json.loads((data / "quality_reviews/hbase12_legacy_lane8/index.json").read_text())
    receipt = json.loads((owned / "receipt.json").read_text())
    manifest = json.loads((owned / "member-sha256.json").read_text())
    result = json.loads((canonical / "result.json").read_text())
    audit = json.loads((canonical / "offline-causal-audit.json").read_text())
    config = json.loads((canonical / "config.json").read_text())
    assert index["schema_version"] == 1 and index["case_id"] == "HBASE-12"
    assert index["classification"] == "expected_exception_oracle_confounded"
    assert index["archive_sha256"] == receipt["archive_sha256"] == digest(archive)
    assert index["receipt_sha256"] == digest(owned / "receipt.json")
    assert index["member_manifest_sha256"] == receipt["member_manifest_sha256"] == digest(owned / "member-sha256.json")
    assert len(manifest) == index["member_count"] == receipt["member_count"] == 652
    for name, source in (("result.json", "terminal-result.json"),
                         ("config.json", "terminal-config.json"),
                         ("offline-causal-audit.json", "node0-offline-causal-audit.json")):
        path = canonical / name
        assert path.read_bytes() == (owned / source).read_bytes()
        assert digest(path) == index[name.removesuffix(".json").replace("offline-causal-audit", "audit") + "_sha256"]
        assert digest(path) == manifest[name]
    assert (canonical / "legacy-preservation-receipt.json").read_bytes() == (owned / "receipt.json").read_bytes()
    assert receipt["schema_version"] == 1 and receipt["case_id"] == "HBASE-12"
    assert receipt["kind"] == "lane8_legacy_terminal_preservation"
    assert receipt["status"] == result["status"] == "budget_exhausted"
    assert result["healthy_seed_valid"] is True
    assert result["runtime_attestation"]["valid"] is True
    for key, expected in (("fault_trials_completed", 80), ("strict_injected_trials", 54),
                          ("strict_target_trials", 48), ("exact_exception_trials", 0),
                          ("duration_seconds", 2847.834)):
        assert result[key] == receipt[key] == expected
    assert result["target_exception_candidate_trials"] == receipt["target_exception_candidate_trials"] == []
    assert result["new_bug"] is None and receipt["hq_admission"] is False
    assert receipt["healthy_junit_status"] == "passed"
    assert receipt["audit_report_gate_passed"] is True
    assert receipt["audit_target_claims_reverified"] is True
    assert receipt["audit_applied_fault_identity_valid"] is True
    assert audit["case_id"] == "HBASE-12" and audit["report_gate_passed"] is True
    assert audit["campaign_result_sha256"] == digest(canonical / "result.json")
    assert audit["target_retained_fault_trials"] == 48
    assert audit["named_applied_faults"] == 54
    assert audit["target_claims_reverified"] is True
    assert audit["applied_fault_identity_valid"] is True
    assert config["core_release"]["release_id"] == receipt["core_release_id"]
    release = baseline / "Mallory/dispatch/releases" / receipt["core_release_id"]
    assert digest(release / "manifest.json") == receipt["core_manifest_sha256"]
    source = Path(config["mapping"]["source_root"]) / (
        "hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/TestRegionMove.java")
    assert digest(source) == receipt["test_source_sha256"]
    text = source.read_text()
    assert "admin.disableTable(tableName);" in text
    assert "catch (DoNotRetryIOException e)" in text
    assert "catches expected DoNotRetryIOException" in receipt["oracle_limit"]
    observed: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            path = Path(member.name)
            assert path.parts and path.parts[0] == "HBASE-12"
            assert ".." not in path.parts and (member.isdir() or member.isfile())
            if not member.isfile():
                continue
            relative = str(Path(*path.parts[1:]))
            assert relative not in observed
            stream = bundle.extractfile(member)
            assert stream is not None
            content = stream.read()
            assert len(content) == member.size
            observed[relative] = hashlib.sha256(content).hexdigest()
            if relative in ("result.json", "config.json", "offline-causal-audit.json"):
                assert content == (canonical / relative).read_bytes()
    assert observed == manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    verify(args.data_root, args.baseline)
    print("HBASE-12 legacy terminal and oracle: verified")
