"""Offline integrity checks for the compact terminal importer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("import_compact_full.py")
SPEC = importlib.util.spec_from_file_location("hbase_descriptor_import", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
IMPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORT)


def encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class CompactImportTest(unittest.TestCase):
    def test_import_verifies_terminal_seal_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "data/mallory"
            case = "HBASE-19"
            campaign = root / case / "campaigns/descriptor-read-v1-full"
            archives = root / "evidence_archives/offhost_full"
            stem = f"{case}-descriptor-read-v1-full"
            files = {
                "result.json": encoded({"case_id": case, "status": "queue_exhausted",
                                        "fault_trials_completed": 2}),
                "config.json": encoded({"case_id": case}),
                "checkpoint.json": encoded({"case_id": case}),
            }
            result_sha = sha(files["result.json"])
            files["offline-causal-audit.json"] = encoded(
                {"case_id": case, "campaign_result_sha256": result_sha})
            manifest = {"case_id": case, "member_count": len(files), "members": [
                {"path": f"{case}/campaigns/descriptor-read-v1-full/{name}",
                 "sha256": sha(data)} for name, data in files.items()]}
            manifest_bytes = encoded(manifest)
            archive_bytes = b"frozen archive verified on node1"
            seal = {"case_id": case, "status": "queue_exhausted",
                    "fault_trials_completed": 2, "raw_host": "node1",
                    "raw_path": str(campaign), "member_count": len(files),
                    "manifest_sha256": sha(manifest_bytes),
                    "archive_sha256": sha(archive_bytes),
                    "archive_bytes": len(archive_bytes),
                    "result_sha256": result_sha,
                    "config_sha256": sha(files["config.json"]),
                    "checkpoint_sha256": sha(files["checkpoint.json"]),
                    "audit_sha256": sha(files["offline-causal-audit.json"])}
            remote_files = {
                str(archives / f"{stem}.receipt.json"): encoded(seal),
                str(archives / f"{stem}.manifest.json"): manifest_bytes,
                **{str(campaign / name): data for name, data in files.items()},
            }

            def remote(*args):
                if args[0] == "cat":
                    return remote_files[args[1]]
                if args[0] == "sha256sum":
                    return (sha(archive_bytes) + "  archive\n").encode()
                if args[0] == "stat":
                    return (str(len(archive_bytes)) + "\n").encode()
                raise AssertionError(args)

            usage = type("Usage", (), {"free": IMPORT.FLOOR + 1000000})()
            with (patch.object(IMPORT, "BASE", base), patch.object(IMPORT, "ROOT", root),
                  patch.object(IMPORT, "remote", side_effect=remote),
                  patch.object(IMPORT.socket, "gethostname", return_value="node0"),
                  patch.object(IMPORT.shutil, "disk_usage", return_value=usage)):
                receipt = IMPORT.import_case(19)
                self.assertEqual(receipt["status"], "queue_exhausted")
                self.assertEqual((root / "cases/HBASE-19/result.json").read_bytes(),
                                 files["result.json"])
                self.assertEqual(IMPORT.import_case(19), receipt)
                remote_files[str(campaign / "result.json")] = b"tampered"
                with self.assertRaises(ValueError):
                    IMPORT.import_case(19)


if __name__ == "__main__":
    unittest.main()
