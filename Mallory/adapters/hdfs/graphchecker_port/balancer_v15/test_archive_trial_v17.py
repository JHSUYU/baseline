import json
import tempfile
import unittest
from pathlib import Path

from .archive_trial_v17 import archive


class ImportedArchiveTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.output, self.raw, self.archives = (base / x for x in
                                               ("output", "raw", "archives"))
        for path in (self.output, self.raw, self.archives):
            path.mkdir()
        self.attempt = self.raw / "attempt-r0017"
        self.attempt.mkdir()
        (self.attempt / "trace.jsonl").write_text("valid\n")
        self.trial = self.output / "trials/r0017"
        self.trial.mkdir(parents=True)
        (self.trial / "result.json").write_text(json.dumps({
            "case_id": "SUCCESSOR", "strict_injection": True}))
        (self.trial / "local-artifacts.json").write_text(json.dumps({
            "local_attempt_dir": str(self.attempt)}))
        self.checkpoint = self.output / "checkpoint.json"
        self.state = {"case_id": "SUCCESSOR", "active": None,
                      "completed_fault_trials": 1,
                      "trials": [{"name": "r0017", "result": "trials/r0017/result.json",
                                  "strict_injection": True}]}
        self.checkpoint.write_text(json.dumps(self.state))

    def test_imported_absolute_index_archives_against_trial_record(self):
        receipt = archive(self.output, self.raw, self.archives, 17)
        self.assertEqual(receipt["trial_index"], 17)
        self.assertTrue(receipt["verified_against_source"])
        self.assertTrue((self.archives / "raw-r0017.tar.gz").is_file())
        self.assertFalse(self.attempt.exists())
        self.assertEqual(archive(self.output, self.raw, self.archives, 17), receipt)

    def test_rejects_missing_exact_trial_record(self):
        self.state["trials"][0]["name"] = "r0001"
        self.checkpoint.write_text(json.dumps(self.state))
        with self.assertRaisesRegex(ValueError, "exact strict accepted"):
            archive(self.output, self.raw, self.archives, 17)

    def test_rejects_active_checkpoint(self):
        self.state["active"] = {"name": "r0018"}
        self.checkpoint.write_text(json.dumps(self.state))
        with self.assertRaisesRegex(ValueError, "inactive checkpoint"):
            archive(self.output, self.raw, self.archives, 17)


if __name__ == "__main__":
    unittest.main()
