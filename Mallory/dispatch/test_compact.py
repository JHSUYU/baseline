"""Lossless scratch compaction and archive replay checks."""

import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from Mallory.dispatch.archive import ensure
from Mallory.dispatch.collect import materialize_campaign_evidence, sha256
from Mallory.dispatch.compact import (archive_and_compact_replay, compact_case,
                                      restore_replay_scratch)


class CompactEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.case = self.root / "cases/HDFS-09"
        self.scratch = self.case / "trials/r0000/scratch/zookeeper/log.1"
        self.scratch.parent.mkdir(parents=True)
        self.payload = b"original MiniCluster scratch\x00" * 100
        self.scratch.write_bytes(self.payload)
        (self.case / "result.json").write_text(json.dumps({
            "case_id": "HDFS-09", "status": "budget_exhausted"}))
        self.archived = ensure(self.root, "campaign", "HDFS-09", reserve_bytes=1)
        self._bind_receipts()

    def _bind_receipts(self):
        result_path = self.case / "result.json"
        result = json.loads(result_path.read_text())
        result["evidence_archive"] = {
            "path": self.archived["archive_relative"],
            "sha256": self.archived["archive_sha256"],
            "manifest_path": self.archived["manifest_relative"],
            "manifest_sha256": self.archived["manifest_sha256"]}
        result_path.write_text(json.dumps(result))
        (self.case / "offline-causal-audit.json").write_text(json.dumps({
            "case_id": "HDFS-09", "campaign_result_sha256": sha256(result_path)}))

    def test_compaction_rehydrates_identical_scratch_bytes(self):
        receipt = compact_case(self.root, "HDFS-09", min_bytes=1)
        self.assertEqual(len(self.payload), receipt["reclaimed_bytes"])
        self.assertFalse(self.scratch.exists())
        materialize_campaign_evidence(
            self.case, self.root / self.archived["archive_relative"],
            self.root / self.archived["manifest_relative"])
        self.assertEqual(self.payload, self.scratch.read_bytes())

    def test_compaction_rejects_changed_expanded_bytes(self):
        self.scratch.write_bytes(b"X" * len(self.payload))
        with self.assertRaisesRegex(ValueError, "archived scratch hash differs"):
            compact_case(self.root, "HDFS-09", min_bytes=1)
        self.assertTrue(self.scratch.exists())

    def test_compaction_rejects_missing_archive_member(self):
        archive = self.root / self.archived["archive_relative"]
        manifest_path = self.root / self.archived["manifest_relative"]
        replacement = archive.with_name("replacement.tar.gz")
        with tarfile.open(archive, "r:gz") as source, tarfile.open(replacement, "w:gz") as output:
            for member in source:
                if member.name == str(self.scratch.relative_to(self.case)):
                    continue
                stream = source.extractfile(member)
                if stream is None:
                    raise AssertionError("fixture archive has a non-file member")
                output.addfile(member, stream)
        os.replace(replacement, archive)
        manifest = json.loads(manifest_path.read_text())
        manifest["archive_sha256"] = sha256(archive)
        manifest_path.write_text(json.dumps(manifest))
        self.archived["archive_sha256"] = sha256(archive)
        self.archived["manifest_sha256"] = sha256(manifest_path)
        self._bind_receipts()
        with self.assertRaisesRegex(ValueError, "archive omitted selected scratch files"):
            compact_case(self.root, "HDFS-09", min_bytes=1)
        self.assertEqual(self.payload, self.scratch.read_bytes())


class ReplayCompactionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.campaign = self.root / "replays/SOLR-05-v4"
        self.scratch = self.campaign / "trials/r0001/scratch/zk/log.1"
        self.scratch.parent.mkdir(parents=True)
        self.payload = b"lossless scratch\x00" * 200
        self.scratch.write_bytes(self.payload)
        (self.campaign / "result.json").write_text(json.dumps({
            "case_id": "SOLR-05", "status": "budget_exhausted"}))
        self.core = {name: name + "-hash" for name in
                     ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")}
        self.release = {"release_id": "test-release", "files": {
            f"Mallory/core/{name}": digest for name, digest in self.core.items()}}
        (self.campaign / "offline-causal-audit.json").write_text(json.dumps({
            "campaign_result_sha256": sha256(self.campaign / "result.json"),
            "core_source_sha256": self.core, "report_gate_passed": True,
            "healthy_observed_path_doors": 1}))

    def _compact(self):
        with mock.patch("Mallory.dispatch.core_release.verify", return_value=self.release):
            return archive_and_compact_replay(self.root, self.campaign, "SOLR-05-v4",
                                              self.root / "release.json", min_bytes=1)

    def test_replay_compaction_rehydrates_byte_for_byte(self):
        receipt = self._compact()
        self.assertEqual(1, receipt["removed_files"])
        self.assertFalse(self.scratch.exists())
        restored = restore_replay_scratch(self.root, self.campaign)
        self.assertEqual(1, restored["restored_files"])
        self.assertEqual(self.payload, self.scratch.read_bytes())
        self.assertEqual(0, restore_replay_scratch(self.root, self.campaign)["restored_files"])

    def test_replay_restore_rejects_missing_archive(self):
        receipt = self._compact()
        (self.root / receipt["archive_relative"]).unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            restore_replay_scratch(self.root, self.campaign)
        self.assertFalse(self.scratch.exists())

    def test_replay_restore_rejects_mismatched_archive(self):
        receipt = self._compact()
        archive = self.root / receipt["archive_relative"]
        with archive.open("ab") as output:
            output.write(b"corrupt")
        with self.assertRaisesRegex(ValueError, "archive hash changed"):
            restore_replay_scratch(self.root, self.campaign)
        self.assertFalse(self.scratch.exists())

if __name__ == "__main__":
    unittest.main()
