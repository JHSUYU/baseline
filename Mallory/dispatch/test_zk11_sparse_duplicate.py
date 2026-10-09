"""Small restore/tamper checks for the ZK11 sparse duplicate receipt."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = (Path(__file__).resolve().parents[2] /
          "data/mallory/dispatch/zk11-sparse-duplicate-v1.py")
SPEC = importlib.util.spec_from_file_location("zk11_sparse_duplicate_v1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SparseDuplicateRestoreTest(unittest.TestCase):
    def test_restore_exact_bytes_and_reject_remote_tamper_or_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / "local"
            remote = root / "remote"
            destination = root / "restored"
            local.mkdir()
            member = Path("trials/r0000/test-data/member.bin")
            source = remote / member
            source.parent.mkdir(parents=True)
            source.write_bytes(b"original\0bytes")
            (local / "result.json").write_text(json.dumps({"status": "budget_exhausted"}))
            (local / "offline-causal-audit.json").write_text(json.dumps({"report_gate_passed": True}))
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({
                "state": "compacted", "result_sha256": digest(local / "result.json"),
                "audit_sha256": digest(local / "offline-causal-audit.json"),
                "files": {str(member): {"bytes": source.stat().st_size,
                                        "sha256": digest(source)}}}))
            with (mock.patch.object(MODULE, "LOCAL", local),
                  mock.patch.object(MODULE, "REMOTE", remote),
                  mock.patch.object(MODULE, "RECEIPT", receipt),
                  mock.patch.object(MODULE, "ssh", side_effect=lambda *args: list(args))):
                self.assertEqual(1, MODULE.restore(destination))
                self.assertEqual(source.read_bytes(), (destination / member).read_bytes())
                source.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "restore failed"):
                    MODULE.restore(root / "tampered")
                self.assertFalse((root / "tampered" / member).exists())
                source.unlink()
                with self.assertRaisesRegex(ValueError, "restore failed"):
                    MODULE.restore(root / "missing")
                self.assertFalse((root / "missing" / member).exists())


if __name__ == "__main__":
    unittest.main()
