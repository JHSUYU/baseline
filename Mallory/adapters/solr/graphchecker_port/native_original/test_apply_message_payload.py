"""The optional native queue overlay must retain source and JUnit authority."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apply_message_payload as adapter


class MessagePayloadOverlayTest(unittest.TestCase):
    def test_patched_source_verifies_and_tampering_fails(self) -> None:
        source = Path("/proj/silentfailure-PG0/mallory/solr-native-e27f44e")
        if not source.is_dir():
            self.skipTest("canonical source is unavailable")
        base = json.loads((adapter.HERE / "source_receipt.json").read_text())
        overlay = json.loads(adapter.RECEIPT.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary)
            for relative in set(base["patched_source_sha256"]) | set(
                    base["unchanged_junit_source_sha256"]):
                original = subprocess.run(
                    ["git", "show", base["source_commit"] + ":" + relative],
                    cwd=source, capture_output=True, check=False)
                if original.returncode and relative.endswith("MalloryHttp.java"):
                    continue
                original.check_returncode()
                dest = staged / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(original.stdout)
            subprocess.run(["git", "apply", str(adapter.HERE /
                            "solr-e27f44e-original-engine.patch")],
                           cwd=staged, check=True)
            target = staged / overlay["path"]
            subprocess.run(["git", "apply", str(adapter.PATCH)],
                           cwd=staged, check=True)
            patched = target.read_bytes()
            with patch.object(adapter.subprocess, "check_output",
                              return_value=overlay["source_commit"]):
                self.assertEqual("verified", adapter.install(staged, True)["status"])
                target.write_bytes(patched + b"// tamper\n")
                with self.assertRaisesRegex(ValueError, "queue source"):
                    adapter.install(staged, True)


if __name__ == "__main__":
    unittest.main()
