"""Remote collector finds terminal attempts in isolated lane state roots."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from Mallory.dispatch.collect import REMOTE_SCAN


class IsolatedLaneScanTest(unittest.TestCase):
    def test_scans_named_dispatch_subdirectory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_id = "HBASE-07"
            attempt = "attempt-1"
            summary = root / "cases" / case_id / "result.json"
            dispatch = (root / "dispatch/node1-hbase-full-lane3/campaign/cases"
                        / case_id)
            evidence = dispatch / "attempts" / attempt
            summary.parent.mkdir(parents=True)
            evidence.mkdir(parents=True)
            summary.write_text(json.dumps({
                "case_id": case_id, "status": "budget_exhausted",
                "last_dispatch_attempt_id": attempt,
                "evidence_archive": {"sha256": "archive-hash"}}))
            (dispatch / "result.json").write_text(json.dumps({
                "case_id": case_id, "attempt_id": attempt,
                "status": "command_succeeded", "scientific_completed": True,
                "scientific_result_status": "budget_exhausted"}))
            (evidence / "exit.json").write_text(json.dumps({
                "case_id": case_id, "attempt_id": attempt, "host": "node1"}))
            (evidence / "spec.json").write_text(json.dumps({
                "case_id": case_id, "attempt_id": attempt, "host": "node1"}))
            def scan():
                process = subprocess.run(
                    [sys.executable, "-c", REMOTE_SCAN, str(root), "node1", "",
                     "node1-hbase-full-lane3"],
                    input=json.dumps([case_id]), capture_output=True, text=True, check=True)
                return json.loads(process.stdout)
            self.assertEqual([], scan(), "owner-host audit must finish before collection")
            (summary.parent / "offline-causal-audit.json").write_text(json.dumps({
                "campaign_result_sha256": hashlib.sha256(summary.read_bytes()).hexdigest(),
                "report_gate_passed": False}))
            rows = scan()
            self.assertEqual(1, len(rows))
            self.assertEqual("archive-hash", rows[0]["summary_archive_sha256"])
            self.assertTrue(any("node1-hbase-full-lane3" in path
                                for path in rows[0]["files"]))


if __name__ == "__main__":
    unittest.main()
