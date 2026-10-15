"""The raw archive must verify contents before deleting a trial directory."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Mallory.adapters.hdfs.graphchecker_port.balancer_short_lifetime_repeat_v1 import archive_trial


class ArchiveTrialTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.output = root / "output"
        self.raw = root / "raw"
        self.archives = root / "archives"
        self.attempt = self.raw / "slot" / "r0001-attempt"
        self.attempt.mkdir(parents=True)
        (self.attempt / "trace.jsonl").write_text('{"event":"check"}\n')
        trial = self.output / "trials/r0001"
        trial.mkdir(parents=True)
        (trial / "result.json").write_text('{"strict_injection":true}')
        (trial / "local-artifacts.json").write_text(json.dumps({
            "local_attempt_dir": str(self.attempt)}))
        (self.output / "checkpoint.json").write_text(json.dumps({
            "completed_fault_trials": 1, "active": None}))

    def test_archive_hash_verification_precedes_deletion(self) -> None:
        with patch.object(archive_trial.subprocess, "run") as pgrep:
            pgrep.return_value.stdout = b""
            receipt = archive_trial.archive(self.output, self.raw,
                                            self.archives, 1)
        self.assertTrue(receipt["verified_against_source"])
        self.assertFalse(self.attempt.exists())
        self.assertEqual(receipt["archive_sha256"], archive_trial.sha(
            self.archives / "raw-r0001.tar.gz"))
        self.assertEqual(receipt["archive_size_bytes"], (
            self.archives / "raw-r0001.tar.gz").stat().st_size)

    def test_outside_raw_root_never_deleted(self) -> None:
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "keep").write_text("evidence")
        (self.output / "trials/r0001/local-artifacts.json").write_text(
            json.dumps({"local_attempt_dir": str(outside)}))
        with patch.object(archive_trial.subprocess, "run") as pgrep:
            pgrep.return_value.stdout = b""
            with self.assertRaisesRegex(ValueError, "escaped"):
                archive_trial.archive(self.output, self.raw, self.archives, 1)
        self.assertEqual("evidence", (outside / "keep").read_text())
        self.assertFalse(self.archives.exists())


if __name__ == "__main__":
    unittest.main()
