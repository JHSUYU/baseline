"""No-JVM terminal and receipt gates for the HDFS-12 offhost collectors."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


NODE2 = load("hdfs12_node2_collector", "collect_hdfs12_node2_full.py")
NODE0 = load("hdfs12_node0_sync", "sync_hdfs12_node0_sparse.py")


class CollectorGatesTest(unittest.TestCase):
    def test_terminal_requires_matching_result_and_checkpoint(self):
        original = NODE2.SOURCE
        with tempfile.TemporaryDirectory(prefix="hdfs12-collector-") as directory:
            NODE2.SOURCE = Path(directory)
            result = {"case_id": "HDFS-12", "status": "running"}
            checkpoint = {"case_id": "HDFS-12", "status": "running", "running": None}
            try:
                (NODE2.SOURCE / "result.json").write_text(json.dumps(result))
                (NODE2.SOURCE / "checkpoint.json").write_text(json.dumps(checkpoint))
                self.assertFalse(NODE2.ready())
                result["status"] = checkpoint["status"] = "budget_exhausted"
                (NODE2.SOURCE / "result.json").write_text(json.dumps(result))
                (NODE2.SOURCE / "checkpoint.json").write_text(json.dumps(checkpoint))
                self.assertTrue(NODE2.ready())
                result["status"] = "queue_exhausted"
                (NODE2.SOURCE / "result.json").write_text(json.dumps(result))
                with self.assertRaisesRegex(RuntimeError, "mismatch"):
                    NODE2.ready()
            finally:
                NODE2.SOURCE = original

    def test_sparse_receipt_rejects_wrong_result_pin(self):
        original = NODE0.ssh
        receipt = {
            "schema_version": 1, "case_id": "HDFS-12", "status": "budget_exhausted",
            "config_sha256": NODE0.CONFIG_SHA, "canonical_result_sha256": "r",
            "audit_sha256": "a", "files": {"config.json": NODE0.CONFIG_SHA,
                                             "result.json": "r",
                                             "offline-causal-audit.json": "a"},
        }
        try:
            NODE0.ssh = lambda *args: subprocess.CompletedProcess(args, 0, json.dumps(receipt), "")
            self.assertEqual(NODE0.remote_receipt(), receipt)
            receipt["files"]["result.json"] = "changed"
            with self.assertRaisesRegex(ValueError, "disagree"):
                NODE0.remote_receipt()
        finally:
            NODE0.ssh = original


if __name__ == "__main__":
    unittest.main()
