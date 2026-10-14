"""A reviewed inspector patch is distinct from executed campaign source."""

import difflib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .frozen_terminal import inspect_frozen_terminal, validated_frozen_audit
from .inspector_overlay import METHOD, MODULE, verify_inspector_overlay
from .queue import sha


class InspectorOverlayTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "executed-source"
        module = self.source / MODULE
        module.parent.mkdir(parents=True)
        (self.source / "Mallory/__init__.py").write_text("")
        (module.parent / "__init__.py").write_text(
            "from .checklist import inspect_case\n")
        self.original = (
            "def inspect_case(item, owner, config_root, state_root):\n"
            "    return {'case_id': item['case_id'], 'owner': owner,\n"
            "            'native_config': item['config'],\n"
            "            'native_tested_complete': True,\n"
            "            'terminal_disposition': 'tested_no_target_throw',\n"
            "            'fault_trials': 1, 'elapsed_seconds': 3.0}\n")
        module.write_text(self.original)
        patched = self.original.replace("'fault_trials': 1,",
                                        "'overlay_marker': True, 'fault_trials': 1,")
        self.patched = self.root / "reviewed-checklist.py"
        self.patched.write_text(patched)
        self.diff = self.root / "reviewed-checklist.patch"
        self.diff.write_text("".join(difflib.unified_diff(
            self.original.splitlines(keepends=True), patched.splitlines(keepends=True),
            fromfile=f"a/{MODULE}", tofile=f"b/{MODULE}")))
        self.source_tar = self.root / "executed-source.tar"
        self.source_tar.write_bytes(b"source archive fixture")
        self.source_pin = {"root_path": str(self.source),
                           "source_tar_path": str(self.source_tar),
                           "source_tar_sha256": sha(self.source_tar),
                           "python_sha256": {str(path.relative_to(self.source)): sha(path)
                                             for path in self.source.rglob("*.py")}}
        self.overlay_pin = {"schema_version": 1, "module": MODULE,
                            "base_sha256": sha(module),
                            "patched_path": str(self.patched),
                            "patched_sha256": sha(self.patched),
                            "diff_path": str(self.diff),
                            "diff_sha256": sha(self.diff),
                            "changed_symbols": ["inspect_case"]}
        self.config_root = self.root / "config"
        self.config_root.mkdir()
        self.state_root = self.root / "state"
        self.state_root.mkdir()
        self.config = self.root / "native-config.json"
        self.config.write_text('{"case_id":"TEST-01"}\n')
        self.binding = self.config_root / "TEST-01.json"
        self._save_binding()
        self.native = self.root / "native"
        for index in range(2):
            trial = self.native / "trials" / f"r{index:04d}"
            trial.mkdir(parents=True)
            (trial / "result.json").write_text(json.dumps({"trial": index}))
        (self.native / "checkpoint.json").write_text(json.dumps({
            "healthy": {"name": "r0000", "result": "trials/r0000/result.json"},
            "trials": [{"name": "r0001", "result": "trials/r0001/result.json"}],
            "completed_fault_trials": 1, "next_trial_index": 2}))
        summary = self.native / "summary.json"
        summary.write_text('{"completed_fault_trials":1,"elapsed_seconds":3.0}\n')
        self.engine = self.root / "engine"
        jar = self.engine / "target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
        jar.parent.mkdir(parents=True)
        jar.write_bytes(b"engine fixture")
        self.item = {"case_id": "TEST-01", "config": str(self.config.resolve())}
        self.fingerprint = {"case_id": "TEST-01", "summary_sha256": sha(summary)}

    def _save_binding(self):
        self.binding.write_text(json.dumps({"campaign_python_source": self.source_pin,
                                            "inspector_overlay": self.overlay_pin}))

    def _inspect(self):
        with patch("Mallory.native_graphchecker_queue.frozen_terminal._native_case_files",
                   return_value=(self.config, self.native)), patch(
                "Mallory.native_graphchecker_queue.frozen_terminal._pinned_engine_root",
                return_value=self.engine), patch(
                "Mallory.native_graphchecker_queue.frozen_terminal._terminal_fingerprint",
                return_value=self.fingerprint):
            return inspect_frozen_terminal(self.item, "node0", self.config_root,
                                           self.state_root)

    def test_full_inspection_and_cache_pin_both_versions(self):
        receipt = self._inspect()
        self.assertEqual(receipt["method"], METHOD)
        self.assertEqual(receipt["row"]["overlay_marker"], True)
        self.assertEqual(receipt["inspector_sha256"], self.overlay_pin["base_sha256"])
        self.assertEqual(receipt["inspector_overlay"]["patched_sha256"],
                         self.overlay_pin["patched_sha256"])
        self.assertEqual(sha(self.source / MODULE), self.overlay_pin["base_sha256"])
        audit_path = self.root / "audit.json"
        audit_path.write_text(json.dumps(receipt))
        with patch("Mallory.native_graphchecker_queue.frozen_terminal._terminal_fingerprint",
                   return_value=self.fingerprint):
            self.assertTrue(validated_frozen_audit(
                self.item, "node0", self.config_root, self.state_root,
                audit_path)["overlay_marker"])
            self.diff.write_text(self.diff.read_text() + "tamper\n")
            with self.assertRaisesRegex(ValueError, "source or trial evidence"):
                validated_frozen_audit(self.item, "node0", self.config_root,
                                       self.state_root, audit_path)

    def test_unreviewed_source_or_patch_change_fails(self):
        self.patched.write_text(self.patched.read_text() + "# changed\n")
        with self.assertRaisesRegex(ValueError, "patched output bytes changed"):
            self._inspect()
        self.patched.write_text(self.original.replace(
            "def inspect_case", "import os\ndef inspect_case"))
        self.overlay_pin["patched_sha256"] = sha(self.patched)
        self.diff.write_text("".join(difflib.unified_diff(
            self.original.splitlines(keepends=True),
            self.patched.read_text().splitlines(keepends=True),
            fromfile=f"a/{MODULE}", tofile=f"b/{MODULE}")))
        self.overlay_pin["diff_sha256"] = sha(self.diff)
        with self.assertRaisesRegex(ValueError, "top-level statement order"):
            verify_inspector_overlay(self.source_pin, self.source, self.overlay_pin)
        self.overlay_pin["base_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "base differs"):
            verify_inspector_overlay(self.source_pin, self.source, self.overlay_pin)

    def test_repinning_a_noncanonical_diff_or_undeclared_symbol_fails(self):
        self.diff.write_text(self.diff.read_text().replace(
            f"a/{MODULE}", "a/other-module.py"))
        self.overlay_pin["diff_sha256"] = sha(self.diff)
        with self.assertRaisesRegex(ValueError, "diff does not produce"):
            verify_inspector_overlay(self.source_pin, self.source, self.overlay_pin)
        self.overlay_pin["diff_sha256"] = "0" * 64
        self.overlay_pin["changed_symbols"] = ["other_function"]
        self.diff.write_text("".join(difflib.unified_diff(
            self.original.splitlines(keepends=True),
            self.patched.read_text().splitlines(keepends=True),
            fromfile=f"a/{MODULE}", tofile=f"b/{MODULE}")))
        self.overlay_pin["diff_sha256"] = sha(self.diff)
        with self.assertRaisesRegex(ValueError, "undeclared symbols"):
            verify_inspector_overlay(self.source_pin, self.source, self.overlay_pin)


if __name__ == "__main__":
    unittest.main()
