import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from solr_junit_runner import source_revision


class SourceRevisionTest(unittest.TestCase):
    def test_clean_copy_without_git_uses_inventory_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, basis = source_revision("SOLR-06", Path(directory))
        self.assertEqual("e27f44e3d78dfcec230c97e0a1240e3751daeff9", revision)
        self.assertEqual("inventory_pinned_clean_copy_dispatch_fingerprint", basis)

    def test_git_head_must_agree_with_inventory(self):
        class GitResult:
            returncode = 0
            stdout = "different-commit\n"
        with patch("solr_junit_runner.subprocess.run", return_value=GitResult()):
            with self.assertRaisesRegex(ValueError, "differs from inventory"):
                source_revision("SOLR-06", Path("/tmp"))


if __name__ == "__main__":
    unittest.main()
