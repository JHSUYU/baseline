#!/usr/bin/env python3
"""Offline regressions for the legacy release integrity gate."""

from pathlib import Path
import shutil
import tempfile
import unittest

from verify_legacy_release import EXPECTED_ID, verify

HERE = Path(__file__).resolve().parent
RELEASE = HERE.parents[5] / "Mallory/dispatch/releases" / EXPECTED_ID


class LegacyReleaseTest(unittest.TestCase):
    def test_pinned_release(self) -> None:
        verdict = verify(RELEASE)
        self.assertEqual(verdict["verified_file_count"], 9)

    def test_reject_changed_core_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / EXPECTED_ID
            shutil.copytree(RELEASE, copy)
            with (copy / "Mallory/core/audit.py").open("a") as handle:
                handle.write("\n# changed\n")
            with self.assertRaisesRegex(ValueError, "file SHA mismatch"):
                verify(copy)

    def test_reject_changed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / EXPECTED_ID
            shutil.copytree(RELEASE, copy)
            with (copy / "manifest.json").open("a") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(ValueError, "manifest SHA mismatch"):
                verify(copy)


if __name__ == "__main__":
    unittest.main()
