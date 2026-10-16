"""Nested frozen healthy lineage and older raw attempt archive receipts."""

from __future__ import annotations

import hashlib
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign
from Mallory.native_graphchecker_campaign import test_bounded_prefix


class NestedBoundedLineageTest(unittest.TestCase):
    def test_inherited_healthy_root_requires_verified_prior_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior_config, frozen, _, _ = test_bounded_prefix.BoundedPrefixImportTest(
                "runTest").frozen_healthy_fixture(root)
            pins = campaign.build_predecessor_pins(
                prior_config, frozen, successor_fault_trials=256,
                successor_max_faults_per_trial=256,
                bounded_snapshot_manifest=frozen /
                "bounded-snapshot-manifest.json", frozen_healthy_seed=True)
            current = root / "current"
            current.mkdir()
            campaign._atomic(current / "config.json", {
                "predecessor_campaign": pins})
            sidecar = frozen / "trials/r0000/local-artifacts.json"
            source = {"predecessor_import": {
                "source_kind": "bounded_prefix_snapshot_v1",
                "source_root": str(frozen),
                "source_pins": {name: pins[name + "_sha256"] for name
                                in ("config", "checkpoint", "summary")},
                "bounded_snapshot_manifest_sha256": pins[
                    "bounded_snapshot_manifest_sha256"],
                "frozen_healthy_seed": {"source_healthy_files": {
                    "trials/r0000/local-artifacts.json":
                    campaign._sha(sidecar)}}}}
            paths = {"config": current / "config.json"}
            local = campaign._load(sidecar)
            self.assertTrue(campaign._inherited_healthy_local_lineage(
                paths, source, sidecar, local))
            # A second bounded successor keeps the first campaign's raw
            # root, while the immediate predecessor has a different output
            # root.  The exact sidecar and verified predecessor chain prove
            # that inheritance without equating the two roots.
            with patch.object(campaign, "_verify_bounded_snapshot",
                              return_value={"source_output_root":
                                            "/intermediate-campaign",
                                            "files": {
                                                "trials/r0000/local-artifacts.json": {
                                                    "sha256": campaign._sha(sidecar)}}}):
                self.assertTrue(campaign._inherited_healthy_local_lineage(
                    paths, source, sidecar, local))
            self.assertFalse(campaign._inherited_healthy_local_lineage(
                paths, source, sidecar,
                {**local, "campaign_root": "/unrelated"}))
            source["predecessor_import"]["frozen_healthy_seed"][
                "source_healthy_files"]["trials/r0000/local-artifacts.json"] = (
                    "0" * 64)
            self.assertFalse(campaign._inherited_healthy_local_lineage(
                paths, source, sidecar, local))

    def test_attempt_contents_requires_member_and_selected_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = root / "r0115-attempt-abc"
            attempt.mkdir()
            payload = attempt / "stdout.log"
            payload.write_bytes(b"pinned raw bytes")
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            archive = root / "raw.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                stream.add(attempt, arcname=attempt.name)
            row = {"absolute_tar_path": str(archive),
                   "archive_sha256": campaign._sha(archive),
                   "archive_format": "attempt_contents"}
            receipt = {"schema_version": 1,
                       "actual_restore_verified": True,
                       "source_retained": True,
                       "archive": str(archive),
                       "archive_sha256": campaign._sha(archive),
                       "archive_bytes": archive.stat().st_size,
                       "source": str(attempt), "source_bytes": payload.stat().st_size,
                       "member_count": 2, "members": [
                           {"path": ".", "type": "dir"},
                           {"path": "stdout.log", "type": "file",
                            "bytes": payload.stat().st_size,
                            "sha256": digest}]}
            local = {"local_attempt_dir": str(attempt),
                     "total_bytes": payload.stat().st_size,
                     "selected_sha256": {"stdout.log": digest}}
            self.assertTrue(campaign._verify_attempt_contents_archive(
                row, receipt, local))
            self.assertFalse(campaign._verify_attempt_contents_archive(
                row, receipt, {**local, "selected_sha256": {
                    "stdout.log": "0" * 64}}))
            self.assertFalse(campaign._verify_attempt_contents_archive(
                row, {**receipt, "source": "/wrong"}, local))
            self.assertFalse(campaign._verify_attempt_contents_archive(
                {**row, "archive_format": "untrusted"}, receipt, local))


if __name__ == "__main__":
    unittest.main()
