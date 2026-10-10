import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TerminalCollectorChecks(unittest.TestCase):
    def test_node2_requires_matching_terminal_checkpoint(self):
        node2 = load("collect_node2")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checkpoint.json").write_text(json.dumps({
                "status": "budget_exhausted", "case_id": "HDFS-19", "running": None}))
            (root / "result.json").write_text(json.dumps({
                "status": "budget_exhausted", "case_id": "HDFS-19"}))
            self.assertTrue(node2.terminal_ready(root, "HDFS-19"))
            self.assertRaises(RuntimeError, node2.terminal_ready, root, "HDFS-20")
            (root / "checkpoint.json").write_text(json.dumps({
                "status": "running", "case_id": "HDFS-19", "running": 1}))
            self.assertFalse(node2.terminal_ready(root, "HDFS-19"))

    def test_manifest_is_sha_bound(self):
        node2 = load("collect_node2")
        with self.assertRaises(RuntimeError):
            node2.settings("HDFS-19", "0" * 64)

    def test_node0_rejects_unbound_receipt(self):
        node0 = load("sync_node0")
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            row = {"node2_state_root": str(state), "config_sha256": "a" * 64}
            (state / "terminal-publication.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-19", "status": "budget_exhausted",
                "config_sha256": "b" * 64, "files": {name: "c" * 64 for name in node0.FILES}}))
            original = node0.ssh
            try:
                class Result:
                    returncode = 0
                    stderr = ""
                    stdout = (state / "terminal-publication.json").read_text()
                node0.ssh = lambda *_args: Result()
                with self.assertRaises(RuntimeError):
                    node0.receipt_or_none("HDFS-19", row)
            finally:
                node0.ssh = original


if __name__ == "__main__":
    unittest.main()
