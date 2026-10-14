"""Archive-backed frozen inspection must fail closed on missing or changed raw."""

import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from .raw_archive import _sha, verify_trial_evidence
from .frozen_terminal import _trial_sha256


class RawArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.raw = base / "raw-123"
        original = self.raw / "raw/r0000/original-graph"
        original.mkdir(parents=True)
        (original / "summary.json").write_text('{"closure": true}\n')
        self.trial = base / "trials/r0000/original-graph"
        self.trial.parent.mkdir(parents=True)
        self.trial.symlink_to(original, target_is_directory=True)
        self.summary = self.trial / "summary.json"
        self.digest = _sha(self.summary)
        self.archive = base / "raw.tar.gz"
        with tarfile.open(self.archive, "w:gz") as tar:
            tar.add(self.raw, arcname=self.raw.name)
        self.receipt = base / "receipt.json"
        self._write_receipt()
        self.binding = {"raw_archive_evidence": {
            "path": str(self.receipt), "sha256": _sha(self.receipt)}}
        self.hashes = {str(self.summary): self.digest}
        self.targets = {str(self.summary): str(original / "summary.json")}

    def _write_receipt(self):
        self.receipt.write_text(json.dumps({
            "schema_version": 1, "case_id": "SOLR-18", "status": "reclaimed",
            "items": [{"raw_dir": str(self.raw), "archive": str(self.archive),
                       "archive_sha256": _sha(self.archive)}]}))

    def test_archived_summary_survives_raw_removal(self):
        self.assertTrue(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))

    def test_frozen_receipt_records_stable_symlink_and_raw_target(self):
        root = self.trial.parents[2]
        result = self.trial.parent / "result.json"
        result.write_text('{"status":"healthy_seed"}\n')
        hashes, targets = _trial_sha256(root, 0)
        self.assertEqual(hashes[str(self.summary)], self.digest)
        self.assertEqual(targets[str(self.summary)], self.targets[str(self.summary)])
        self.assertNotIn(str(self.summary.resolve()), targets)
        shutil.rmtree(self.raw)
        self.assertTrue(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))

    def test_archive_tamper_and_unpinned_missing_raw_fail(self):
        shutil.rmtree(self.raw)
        self.assertFalse(verify_trial_evidence(
            {}, "SOLR-18", self.hashes, self.targets))
        self.archive.write_bytes(self.archive.read_bytes() + b"tamper")
        self.assertFalse(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))

    def test_changed_live_summary_never_falls_back(self):
        (self.raw / "raw/r0000/original-graph/summary.json").write_text(
            '{"closure": false}\n')
        self.assertFalse(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))

    def test_changed_symlink_or_receipt_fails(self):
        shutil.rmtree(self.raw)
        self.trial.unlink()
        self.trial.symlink_to(self.raw / "other", target_is_directory=True)
        self.assertFalse(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))
        self.trial.unlink()
        self.trial.symlink_to(self.raw / "raw/r0000/original-graph",
                              target_is_directory=True)
        self.receipt.write_text(self.receipt.read_text() + " ")
        self.assertFalse(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))
