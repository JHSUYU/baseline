"""The sealed inspector runs from the bound source, with no JUnit replay."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .frozen_terminal import inspect_frozen_terminal, validated_frozen_audit
from .queue import sha


class FrozenTerminalTest(unittest.TestCase):
    def test_source_pin_and_separate_inspector_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_root = root / "config"
            config_root.mkdir()
            state_root = root / "state"
            state_root.mkdir()
            source = root / "source"
            module = source / "Mallory/native_graphchecker_dispatch/checklist.py"
            module.parent.mkdir(parents=True)
            (source / "Mallory/__init__.py").write_text("")
            (module.parent / "__init__.py").write_text("")
            module.write_text("def inspect_case(item, owner, config_root, state_root):\n"
                              "    return {'case_id': item['case_id'], 'owner': owner, "
                              "'native_config': item['config'], "
                              "'native_tested_complete': True, "
                              "'terminal_disposition': 'tested_no_target_throw', "
                              "'fault_trials': 1, 'elapsed_seconds': 3.0}\n")
            archive = root / "source.tar"
            archive.write_bytes(b"sealed source archive fixture")
            source_hashes = {str(path.relative_to(source)): sha(path)
                             for path in source.rglob("*.py")}
            config = root / "native-config.json"
            config.write_text('{"case_id":"TEST-01"}\n')
            binding = config_root / "TEST-01.json"
            binding.write_text(json.dumps({"campaign_python_source": {
                "root_path": str(source), "source_tar_path": str(archive),
                "source_tar_sha256": sha(archive),
                "python_sha256": source_hashes}}))
            native = root / "native"
            (native / "trials/r0000").mkdir(parents=True)
            (native / "trials/r0001").mkdir()
            for index in range(2):
                (native / "trials" / f"r{index:04d}" / "result.json").write_text(
                    json.dumps({"trial": index}))
            (native / "checkpoint.json").write_text(json.dumps({
                "healthy": {"name": "r0000", "result": "trials/r0000/result.json"},
                "trials": [{"name": "r0001", "result": "trials/r0001/result.json"}],
                "completed_fault_trials": 1, "next_trial_index": 2}))
            (native / "summary.json").write_text(json.dumps({
                "completed_fault_trials": 1, "elapsed_seconds": 3.0}))
            engine = root / "engine"
            jar = engine / "target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"engine fixture")
            item = {"case_id": "TEST-01", "config": str(config.resolve())}
            fingerprint = {"case_id": "TEST-01", "summary_sha256": sha(
                native / "summary.json")}
            with patch("Mallory.native_graphchecker_queue.frozen_terminal._native_case_files",
                       return_value=(config, native)), patch(
                "Mallory.native_graphchecker_queue.frozen_terminal._pinned_engine_root",
                return_value=engine), patch(
                "Mallory.native_graphchecker_queue.frozen_terminal._terminal_fingerprint",
                return_value=fingerprint):
                receipt = inspect_frozen_terminal(item, "node0", config_root,
                                                  state_root)
                self.assertEqual(receipt["row"]["fault_trials"], 1)
                self.assertEqual(receipt["source_tar_sha256"], sha(archive))
                self.assertEqual(len(receipt["trial_evidence_sha256"]), 2)
                audit = root / "sealed-audit.json"
                audit.write_text(json.dumps(receipt))
                # This gate uses the pinned engine and inspector, even when
                # the current process has no working default engine path.
                self.assertEqual(validated_frozen_audit(
                    item, "node0", config_root, state_root, audit),
                    receipt["row"])
                with self.assertRaisesRegex(ValueError, "wrong case or verdict"):
                    validated_frozen_audit(item, "node1", config_root,
                                           state_root, audit)
                jar.write_bytes(b"changed engine")
                with self.assertRaisesRegex(ValueError, "source or trial evidence"):
                    validated_frozen_audit(item, "node0", config_root,
                                           state_root, audit)
                jar.write_bytes(b"engine fixture")
                module.write_text(module.read_text() + "# changed\n")
                with self.assertRaisesRegex(ValueError, "source changed"):
                    inspect_frozen_terminal(item, "node0", config_root,
                                            state_root)
                binding_doc = json.loads(binding.read_text())
                binding_doc["campaign_python_source"]["python_sha256"].pop(
                    "Mallory/native_graphchecker_dispatch/checklist.py")
                binding.write_text(json.dumps(binding_doc))
                with self.assertRaisesRegex(ValueError, "lacks original native inspector"):
                    inspect_frozen_terminal(item, "node0", config_root,
                                            state_root)


if __name__ == "__main__":
    unittest.main()
