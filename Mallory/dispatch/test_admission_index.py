"""Admission needs SHA-bound proof before it can suppress a checklist item."""

from __future__ import annotations

import json
import gzip
import hashlib
from pathlib import Path
import tempfile
import unittest

from Mallory.dispatch.admission_index import _complete_case, _healthy_proof, _source_gap
from Mallory.dispatch.collect import sha256


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class AdmissionIndexTest(unittest.TestCase):
    def test_source_gap_is_bound_to_review_and_zero_door_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            data_root = repo / "data/mallory"
            healthy = data_root / "calibration_v8/HBASE-19/result.json"
            audit_path = healthy.parent / "offline-causal-audit.json"
            write_json(healthy, {"case_id": "HBASE-19", "status": "calibration_complete"})
            write_json(audit_path, {"healthy_observed_path_doors": 0})
            review_path = repo / "Mallory/cases/revisions/hbase-gap.json"
            write_json(review_path, {
                "status": "no_suitable_existing_cluster_test_identified",
                "cases": [{"case_id": "HBASE-19",
                           "current_healthy_result": str(healthy.relative_to(repo)),
                           "current_healthy_result_sha256": sha256(healthy),
                           "current_offline_audit": str(audit_path.relative_to(repo)),
                           "current_offline_audit_sha256": sha256(audit_path)}]})
            write_json(data_root / "source_gaps/HBASE-19/receipt.json", {
                "schema_version": 1, "case_id": "HBASE-19",
                "status": "no_suitable_cluster_test",
                "review_path": str(review_path.relative_to(repo)),
                "review_sha256": sha256(review_path),
                "healthy_result_sha256": sha256(healthy),
                "audit_sha256": sha256(audit_path)})
            self.assertIsNotNone(_source_gap(repo, data_root, "HBASE-19"))
            write_json(audit_path, {"healthy_observed_path_doors": 1})
            self.assertIsNone(_source_gap(repo, data_root, "HBASE-19"))

    def test_healthy_seed_requires_observed_path_and_bound_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "calibration" / "HBASE-02"
            result_path = path / "result.json"
            audit_path = path / "offline-causal-audit.json"
            write_json(result_path, {"case_id": "HBASE-02", "status": "calibration_complete",
                                     "healthy_seed_valid": True, "fault_trials_completed": 0})
            audit = {"campaign_result_sha256": sha256(result_path),
                     "core_source_sha256": {"audit.py": "pinned"},
                     "report_gate_passed": True, "healthy_closure_proven": True,
                     "healthy_observed_path_doors": 1}
            write_json(audit_path, audit)
            self.assertIsNotNone(_healthy_proof(path, "HBASE-02", {"audit.py": "pinned"}))
            audit["healthy_observed_path_doors"] = 0
            write_json(audit_path, audit)
            self.assertIsNone(_healthy_proof(path, "HBASE-02", {"audit.py": "pinned"}))
            audit["healthy_observed_path_doors"] = 1
            audit["campaign_result_sha256"] = "wrong"
            write_json(audit_path, audit)
            self.assertIsNone(_healthy_proof(path, "HBASE-02", {"audit.py": "pinned"}))

    def test_external_terminal_requires_archive_and_unchanged_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            path = data_root / "cases" / "SOLR-05"
            result_path = path / "result.json"
            audit_path = path / "offline-causal-audit.json"
            archive = data_root / "evidence_archives" / "replays" / "SOLR-05.tar.gz"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"lossless archive")
            manifest = archive.with_name("SOLR-05.manifest.json")
            manifest.write_bytes(b"member hashes")
            write_json(result_path, {"case_id": "SOLR-05", "status": "budget_exhausted",
                                     "duration_seconds": 123.5})
            write_json(audit_path, {"campaign_result_sha256": sha256(result_path),
                                    "core_source_sha256": {"audit.py": "pinned"},
                                    "report_gate_passed": True,
                                    "healthy_observed_path_doors": 22})
            receipt = {"result_sha256": sha256(result_path),
                       "audit_sha256": sha256(audit_path),
                       "archive_relative": str(archive.relative_to(data_root)),
                       "archive_sha256": sha256(archive),
                       "manifest_sha256": sha256(manifest)}
            write_json(path / "evidence-compaction.json", receipt)
            completed = _complete_case(path, "SOLR-05", {"audit.py": "pinned"}, data_root)
            self.assertIsNotNone(completed)
            self.assertEqual(123.5, completed["duration_seconds"])
            archive.write_bytes(b"damaged archive")
            self.assertIsNone(_complete_case(path, "SOLR-05", {"audit.py": "pinned"},
                                              data_root))
            archive.write_bytes(b"lossless archive")
            write_json(audit_path, {**json.loads(audit_path.read_text()),
                                    "healthy_observed_path_doors": 0})
            self.assertIsNone(_complete_case(path, "SOLR-05", {"audit.py": "pinned"},
                                              data_root))

    def test_publish_receipt_binds_decompressed_events_and_trial(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            path = data_root / "cases" / "HDFS-01"
            result_path = path / "result.json"
            audit_path = path / "offline-causal-audit.json"
            trial = path / "trials" / "r0000"
            write_json(result_path, {"case_id": "HDFS-01", "status": "budget_exhausted"})
            write_json(audit_path, {"campaign_result_sha256": sha256(result_path),
                                    "core_source_sha256": {"audit.py": "pinned"},
                                    "report_gate_passed": True,
                                    "healthy_observed_path_doors": 1, "trial_count": 1})
            write_json(trial / "result.json", {"trial_id": 0})
            events = b'{"type":"TARGET_CHECK"}\n'
            with gzip.open(trial / "events.jsonl.gz", "wb") as stream:
                stream.write(events)
            write_json(path / "publish-receipt.json", {
                "result_sha256": sha256(result_path),
                "validated_trials": [{"trial_id": 0,
                                      "result_sha256": sha256(trial / "result.json"),
                                      "events_sha256": hashlib.sha256(events).hexdigest()}]})
            self.assertIsNotNone(_complete_case(path, "HDFS-01", {"audit.py": "pinned"},
                                                 data_root))
            with gzip.open(trial / "events.jsonl.gz", "wb") as stream:
                stream.write(b'{"type":"ALTERED"}\n')
            self.assertIsNone(_complete_case(path, "HDFS-01", {"audit.py": "pinned"},
                                              data_root))


if __name__ == "__main__":
    unittest.main()
