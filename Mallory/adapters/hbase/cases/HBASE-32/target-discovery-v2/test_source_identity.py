#!/usr/bin/env python3
"""Offline tests for HBASE-32 source provenance across copied worktrees."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "hbase32_preflight", Path(__file__).with_name("preflight.py"))
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


class SourceIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "Target.java").write_text("class Target {}\n")
        (self.root / ".git").write_text(
            f"gitdir: {self.root / 'absent-worktree-metadata'}\n")
        digest, count = PREFLIGHT.source_snapshot(self.root)
        self.manifest = {
            "source_commit": "a" * 40,
            "source_snapshot": {
                "algorithm": "sha256-path-mode-content-v1",
                "file_count": count,
                "git_pointer_sha256": PREFLIGHT.sha(self.root / ".git"),
                "git_tree": "b" * 40,
                "sha256": digest,
            },
        }

    def test_copied_checkout_requires_full_snapshot(self) -> None:
        result = PREFLIGHT.verify_source_identity(
            self.root, self.manifest, self.manifest["source_snapshot"])
        self.assertEqual(result["source_identity_method"],
                         "full-snapshot-missing-worktree-metadata")
        self.assertEqual(result["source_snapshot_file_count"], 1)
        (self.root / "src" / "Target.java").write_text("class Changed {}\n")
        with self.assertRaisesRegex(ValueError, "source snapshot changed"):
            PREFLIGHT.verify_source_identity(
                self.root, self.manifest, self.manifest["source_snapshot"])

    def test_extra_or_executable_changed_file_rejected(self) -> None:
        source = self.root / "src" / "Target.java"
        source.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "source snapshot changed"):
            PREFLIGHT.verify_source_identity(
                self.root, self.manifest, self.manifest["source_snapshot"])
        source.chmod(0o644)
        (self.root / "src" / "Extra.java").write_text("class Extra {}\n")
        with self.assertRaisesRegex(ValueError, "source snapshot changed"):
            PREFLIGHT.verify_source_identity(
                self.root, self.manifest, self.manifest["source_snapshot"])

    def test_existing_broken_git_metadata_cannot_use_snapshot_fallback(self) -> None:
        (self.root / "absent-worktree-metadata").mkdir()
        with mock.patch.object(PREFLIGHT.subprocess, "check_output",
                               side_effect=PREFLIGHT.subprocess.CalledProcessError(
                                   128, "git")):
            with self.assertRaises(PREFLIGHT.subprocess.CalledProcessError):
                PREFLIGHT.verify_source_identity(
                    self.root, self.manifest, self.manifest["source_snapshot"])

    def test_git_pointer_change_rejected(self) -> None:
        (self.root / ".git").write_text("gitdir: /different/worktree\n")
        with self.assertRaisesRegex(ValueError, "Git worktree pointer changed"):
            PREFLIGHT.verify_source_identity(
                self.root, self.manifest, self.manifest["source_snapshot"])


if __name__ == "__main__":
    unittest.main()
