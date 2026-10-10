"""Bounded tests for HDFS-26 terminal-only sparse publication."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SYNC = load("hdfs26_sparse_sync", ROOT / "sync_hdfs26_node0_sparse.py")
COLLECT = load("hdfs26_collect", ROOT / "collect_hdfs26_node2_full.py")


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


class SparsePublicationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.owner = self.base / "node2"
        self.case = self.owner / "cases/HDFS-26"
        self.state = self.owner / "dispatch/node2-hdfs26-v2-full"
        self.archive = self.state / "publication/evidence_archives/campaign/HDFS-26.tar.gz"
        self.manifest = self.archive.with_suffix(".manifest.json")
        self.copy_receipt = self.state / "raw-copy-receipt.json"
        self.publication = self.state / "terminal-publication.json"
        self.local = self.base / "node0"
        self.local.mkdir()
        self.canonical = self.local / "cases/HDFS-26"
        self.import_state = self.local / "dispatch/node0-hdfs26-v2-full"
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(b"remote full evidence archive")
        write(self.case / "config.json", {"case_id": "HDFS-26"})
        write(self.case / "result.json", {
            "case_id": "HDFS-26", "status": "budget_exhausted",
            "evidence_archive": {"sha256": SYNC.sha(self.archive)}})
        result_sha = SYNC.sha(self.case / "result.json")
        write(self.case / "offline-causal-audit.json", {
            "campaign_result_sha256": result_sha, "report_gate_passed": True})
        raw_result_sha = "a" * 64
        raw_files = {"config.json": SYNC.sha(self.case / "config.json"),
                     "result.json": raw_result_sha,
                     "trials/r0000/result.json": "b" * 64}
        write(self.copy_receipt, {
            "case_id": "HDFS-26", "config_sha256": SYNC.CONFIG_SHA,
            "files": raw_files})
        write(self.manifest, {
            "case_id": "HDFS-26", "phase": "campaign",
            "source_result_sha256": raw_result_sha,
            "archive_sha256": SYNC.sha(self.archive),
            "members": sorted(raw_files)})
        self.receipt = {
            "schema_version": 1, "case_id": "HDFS-26", "status": "budget_exhausted",
            "config_sha256": SYNC.CONFIG_SHA,
            "canonical_result_sha256": result_sha,
            "raw_result_sha256": raw_result_sha,
            "audit_sha256": SYNC.sha(self.case / "offline-causal-audit.json"),
            "archive_path": str(self.archive), "archive_sha256": SYNC.sha(self.archive),
            "archive_bytes": self.archive.stat().st_size,
            "archive_manifest_path": str(self.manifest),
            "archive_manifest_sha256": SYNC.sha(self.manifest),
            "files": {name: SYNC.sha(self.case / name) for name in SYNC.FILES},
        }
        # The fixture's config is intentionally small; pin its real digest.
        self.receipt["config_sha256"] = SYNC.sha(self.case / "config.json")
        self.copy_receipt = self.state / "raw-copy-receipt.json"
        raw = json.loads(self.copy_receipt.read_text())
        raw["config_sha256"] = self.receipt["config_sha256"]
        write(self.copy_receipt, raw)
        write(self.publication, self.receipt)

    def _publish(self):
        def copy(source: Path, destination: Path):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        with (patch.object(SYNC, "BASE", self.local),
              patch.object(SYNC, "STATE", self.import_state),
              patch.object(SYNC, "CANONICAL", self.canonical),
              patch.object(SYNC, "REMOTE_STATE", self.state),
              patch.object(SYNC, "REMOTE_CASE", self.case),
              patch.object(SYNC, "CONFIG_SHA", self.receipt["config_sha256"]),
              patch.object(SYNC, "FLOOR", 0), patch.object(SYNC, "HEADROOM", 0),
              patch.object(SYNC, "verify_remote_archive", lambda _: None),
              patch.object(SYNC, "remote_size", lambda path: path.stat().st_size),
              patch.object(SYNC, "fetch", copy)):
            SYNC.publish(self.receipt)

    def test_terminal_sparse_publication_has_no_trial_trace(self):
        self._publish()
        self.assertTrue((self.canonical / "result.json").is_file())
        self.assertTrue((self.canonical / "offline-causal-audit.json").is_file())
        self.assertTrue((self.canonical / "sync-receipt.json").is_file())
        self.assertFalse((self.canonical / "trials").exists())
        self._publish()  # A watcher restart is idempotent.

    def test_tampered_archive_manifest_does_not_publish(self):
        value = json.loads(self.manifest.read_text())
        value["members"] = ["result.json"]
        write(self.manifest, value)
        self.receipt["archive_manifest_sha256"] = SYNC.sha(self.manifest)
        write(self.publication, self.receipt)
        with self.assertRaisesRegex(ValueError, "complete raw file list"):
            self._publish()
        self.assertFalse(self.canonical.exists())

    def test_collect_ready_requires_terminal_checkpoint(self):
        output = self.base / "raw"
        write(output / "result.json", {"case_id": "HDFS-26", "status": "budget_exhausted"})
        write(output / "checkpoint.json", {
            "case_id": "HDFS-26", "status": "in_progress", "running": None})
        with patch.object(COLLECT, "SOURCE", output):
            self.assertFalse(COLLECT.ready())
            write(output / "checkpoint.json", {
                "case_id": "HDFS-26", "status": "budget_exhausted", "running": None})
            self.assertTrue(COLLECT.ready())


if __name__ == "__main__":
    unittest.main()
