"""Archive-backed frozen inspection must fail closed on missing or changed raw."""

import json
import io
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

    def test_ready_for_reclaim_checks_every_manifest_member(self):
        extra = self.raw / "raw/r0000/trace/runtime_trace.jsonl"
        extra.parent.mkdir(parents=True)
        extra.write_text('{"event":"healthy"}\n')
        with tarfile.open(self.archive, "w:gz") as tar:
            tar.add(self.raw, arcname=self.raw.name)
        files = []
        for path in sorted(self.raw.rglob("*")):
            if path.is_file():
                files.append({"path": path.relative_to(self.raw).as_posix(),
                              "sha256": _sha(path), "size": path.stat().st_size,
                              "type": "file"})
        manifest = self.raw.parent / "manifest.json"
        manifest.write_text(json.dumps({"base": str(self.raw), "files": files}))
        self.receipt.write_text(json.dumps({
            "schema_version": 1, "case_id": "SOLR-18",
            "status": "ready_for_reclaim", "items": [{
                "raw_dir": str(self.raw), "archive": str(self.archive),
                "archive_sha256": _sha(self.archive),
                "manifest_path": str(manifest),
                "manifest_sha256": _sha(manifest),
                "verified_file_count": len(files)}]}))
        self.binding["raw_archive_evidence"]["sha256"] = _sha(self.receipt)
        self.assertTrue(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))
        shutil.rmtree(self.raw)
        self.assertTrue(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))

        # Even a file outside the trial summary must remain exact after raw
        # removal; a newly pinned archive cannot conceal changed trace bytes.
        changed = self.raw.parent / "changed.tar.gz"
        with tarfile.open(self.archive, "r:gz") as src, tarfile.open(
                changed, "w:gz") as dst:
            for member in src:
                if member.isfile():
                    data = src.extractfile(member).read()
                    if member.name.endswith("runtime_trace.jsonl"):
                        data = b"X" + data[1:]
                    dst.addfile(member, io.BytesIO(data))
                else:
                    dst.addfile(member)
        self.receipt.write_text(json.dumps({
            "schema_version": 1, "case_id": "SOLR-18",
            "status": "ready_for_reclaim", "items": [{
                "raw_dir": str(self.raw), "archive": str(changed),
                "archive_sha256": _sha(changed),
                "manifest_path": str(manifest),
                "manifest_sha256": _sha(manifest),
                "verified_file_count": len(files)}]}))
        self.binding["raw_archive_evidence"]["sha256"] = _sha(self.receipt)
        self.assertFalse(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))

    def test_ready_for_reclaim_requires_pinned_manifest(self):
        self.receipt.write_text(json.dumps({
            "schema_version": 1, "case_id": "SOLR-18",
            "status": "ready_for_reclaim", "items": [{
                "raw_dir": str(self.raw), "archive": str(self.archive),
                "archive_sha256": _sha(self.archive)}]}))
        self.binding["raw_archive_evidence"]["sha256"] = _sha(self.receipt)
        self.assertFalse(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))

    def test_ancestor_symlink_alias_survives_raw_reclamation(self):
        alias = self.raw.parent / "run-alias"
        alias.symlink_to(self.raw.parent, target_is_directory=True)
        alias_target = alias / self.raw.name / "raw/r0000/original-graph"
        self.trial.unlink()
        self.trial.symlink_to(alias_target, target_is_directory=True)
        self.targets[str(self.summary)] = str(alias_target / "summary.json")
        self.assertTrue(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))
        shutil.rmtree(self.raw)
        self.assertTrue(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))
        alias.unlink()
        self.assertFalse(verify_trial_evidence(
            self.binding, "SOLR-18", self.hashes, self.targets))
