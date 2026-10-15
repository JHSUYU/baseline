import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from Mallory.adapters.hdfs.graphchecker_port.balancer_v15.freeze_bounded_prefix_v16 import freeze


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FreezeBoundedPrefixTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.archives, self.destination = (root / name for name in
                                                         ("source", "archives", "snapshot"))
        self.source.mkdir()
        self.archives.mkdir()
        (self.source / ".campaign.lock").touch()
        self.config = root / "source-config.json"
        self.config.write_text("{}")
        checkpoint = {"case_id": "CASE", "config_sha256": digest(self.config),
                      "status": "bounded_checkpoint_stop", "terminal": False,
                      "active": None, "completed_fault_trials": 1,
                      "next_trial_index": 2, "trials": [{}], "queue": [],
                      "seen_plan_keys": ["a"]}
        (self.source / "checkpoint.json").write_text(json.dumps(checkpoint))
        (self.source / "summary.json").write_text(json.dumps({
            key: checkpoint[key] for key in ("case_id", "config_sha256", "status",
                                         "completed_fault_trials")}))
        sidecars = {
            "iteration-native/fault-events.jsonl": "events\n",
            "local-artifacts.json": "{}",
            "native-summary.json": "{}",
            "peer-ranking-receipt.json": "{}",
        }
        pins = {"iteration-native/fault-events.jsonl": "fault_events_sha256",
                "local-artifacts.json": "local_artifacts_manifest_sha256",
                "native-summary.json": "native_session_sha256",
                "peer-ranking-receipt.json": "peer_ranking_receipt_sha256"}
        for number in (0, 1):
            trial = self.source / "trials" / f"r{number:04d}"
            trial.mkdir(parents=True)
            result = {"case_id": "CASE"}
            for rel, data in sidecars.items():
                path = trial / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
                result[pins[rel]] = digest(path)
            result_path = trial / "result.json"
            result_path.write_text(json.dumps(result))
            tar = self.archives / f"raw-r{number:04d}.tar.gz"
            tar.write_bytes(b"lossless archive mock")
            receipt = {"trial_index": number, "verified_against_source": True,
                       "archive_sha256": digest(tar),
                       "result_sha256": digest(result_path)}
            (self.archives / f"raw-r{number:04d}-receipt.json").write_text(json.dumps(receipt))

    def test_freezes_exact_prefix(self):
        manifest = freeze(self.source, self.config, self.archives, self.destination, 1)
        self.assertEqual(manifest["completed_fault_trials"], 1)
        self.assertEqual(manifest["source_checkpoint_before_sha256"],
                         manifest["source_checkpoint_after_sha256"])
        self.assertEqual(len(manifest["raw_archives"]), 2)
        self.assertEqual(len(manifest["files"]), 13)
        self.assertTrue((self.destination / "bounded-snapshot-manifest.json").is_file())
        self.assertEqual(digest(self.destination / "checkpoint.json"),
                         manifest["checkpoint_sha256"])

    def test_rejects_archive_mismatch_without_publishing(self):
        (self.archives / "raw-r0001.tar.gz").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "archive receipt mismatch"):
            freeze(self.source, self.config, self.archives, self.destination, 1)
        self.assertFalse(self.destination.exists())

    def test_unmatched_trial_may_lack_peer_receipt_if_result_does(self):
        trial = self.source / "trials/r0001"
        result_path = trial / "result.json"
        result = json.loads(result_path.read_text())
        result.pop("peer_ranking_receipt_sha256")
        result_path.write_text(json.dumps(result))
        (trial / "peer-ranking-receipt.json").unlink()
        receipt_path = self.archives / "raw-r0001-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["result_sha256"] = digest(result_path)
        receipt_path.write_text(json.dumps(receipt))
        manifest = freeze(self.source, self.config, self.archives, self.destination, 1)
        self.assertNotIn("trials/r0001/peer-ranking-receipt.json", manifest["files"])

    def test_rejects_active_checkpoint(self):
        path = self.source / "checkpoint.json"
        checkpoint = json.loads(path.read_text())
        checkpoint["active"] = {"index": 2}
        path.write_text(json.dumps(checkpoint))
        with self.assertRaisesRegex(ValueError, "inactive bounded prefix"):
            freeze(self.source, self.config, self.archives, self.destination, 1)


if __name__ == "__main__":
    unittest.main()
