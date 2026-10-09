"""External audited predecessor receipts must bind exact raw evidence."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from Mallory.dispatch import external_predecessor
from Mallory.dispatch.collect import sha256


class ExternalPredecessorTest(unittest.TestCase):
    def test_hash_bound_audited_terminal_predecessor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_path = root / "result.json"
            audit_path = root / "offline-causal-audit.json"
            receipt_path = root / "receipt.json"
            result_path.write_text(json.dumps({"case_id": "HBASE-01",
                                               "status": "budget_exhausted",
                                               "fault_trials_completed": 80}))
            names = ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")
            core_hashes = {f"Mallory/core/{name}": "a" * 64 for name in names}
            audit_path.write_text(json.dumps({
                "case_id": "HBASE-01", "terminal_status": "budget_exhausted",
                "campaign_result_sha256": sha256(result_path),
                "report_gate_passed": True, "healthy_closure_proven": True,
                "healthy_observed_path_doors": 1,
                "core_source_sha256": {name: "a" * 64 for name in names}}))
            receipt_path.write_text(json.dumps({
                "schema_version": 1, "case_id": "HBASE-01",
                "core_release_id": "release",
                "result_sha256": sha256(result_path),
                "audit_sha256": sha256(audit_path)}))
            release = {"release_id": "release", "files": core_hashes}
            with mock.patch.object(external_predecessor, "verify_core_release",
                                   return_value=release):
                self.assertEqual("HBASE-01", external_predecessor.verify(
                    receipt_path, root / "manifest.json")["case_id"])
                audit_path.write_text(audit_path.read_text() + " ")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    external_predecessor.verify(receipt_path, root / "manifest.json")


if __name__ == "__main__":
    unittest.main()
