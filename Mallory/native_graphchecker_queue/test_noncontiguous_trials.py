"""Sealed checkpoints, rather than ordinal guesses, identify completed trials."""

import json
import tempfile
import unittest
from pathlib import Path

from Mallory.native_graphchecker_dispatch.checklist import _checkpoint_trial_refs
from .frozen_terminal import _trial_sha256
from .queue import sha


class NoncontiguousTrialsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkpoint = {
            "healthy": {"name": "r0000", "result": "trials/r0000/result.json"},
            "trials": [
                {"name": "r0002", "result": "trials/r0002/result.json"},
                {"name": "r0003", "result": "trials/r0003/result.json"},
            ],
            "completed_fault_trials": 2,
            "next_trial_index": 4,
        }
        for name in ("r0000", "r0002", "r0003"):
            trial = self.root / "trials" / name
            trial.mkdir(parents=True)
            (trial / "result.json").write_text(json.dumps({"name": name}))
        self._save()

    def _save(self):
        (self.root / "checkpoint.json").write_text(json.dumps(self.checkpoint))

    def test_gap_is_preserved_in_hash_receipt(self):
        refs = _checkpoint_trial_refs(self.root, self.checkpoint)
        self.assertEqual([path.parent.name for _, path in refs],
                         ["r0000", "r0002", "r0003"])
        hashes, targets = _trial_sha256(self.root, 2)
        self.assertEqual(targets, {})
        self.assertEqual(set(hashes), {str(path) for _, path in refs})
        self.assertEqual(hashes[str(refs[-1][1])], sha(refs[-1][1]))
        self.assertFalse((self.root / "trials/r0001/result.json").exists())

    def test_reordered_duplicate_and_wrong_path_fail(self):
        self.checkpoint["trials"].reverse()
        self._save()
        with self.assertRaisesRegex(ValueError, "order"):
            _trial_sha256(self.root, 2)
        self.checkpoint["trials"] = [self.checkpoint["trials"][0]] * 2
        self._save()
        with self.assertRaisesRegex(ValueError, "order"):
            _trial_sha256(self.root, 2)
        self.checkpoint["trials"] = [
            {"name": "r0002", "result": "trials/r0003/result.json"},
            {"name": "r0003", "result": "trials/r0003/result.json"},
        ]
        self._save()
        with self.assertRaisesRegex(ValueError, "result path"):
            _trial_sha256(self.root, 2)

    def test_missing_extra_and_count_mismatch_fail(self):
        with self.assertRaisesRegex(ValueError, "count"):
            _trial_sha256(self.root, 3)
        extra = self.root / "trials/r0001/result.json"
        extra.parent.mkdir()
        extra.write_text("{}")
        with self.assertRaisesRegex(ValueError, "extra"):
            _trial_sha256(self.root, 2)
        extra.unlink()
        (self.root / "trials/r0002/result.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            _trial_sha256(self.root, 2)


if __name__ == "__main__":
    unittest.main()
