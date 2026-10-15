import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import guarded_phase_v17 as phase


class GuardedPhaseTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.pg0, self.output, self.raw, self.work = (root / x for x in
                                                     ("pg0", "output", "raw", "work"))
        for path in (self.pg0, self.output, self.raw, self.work):
            path.mkdir()
        self.config = root / "config.json"
        self.config.write_text(json.dumps({"case_id": "SUCCESSOR", "runner": {
            "local_artifact_root": str(self.raw), "local_work_root": str(self.work)}}))
        self.args = argparse.Namespace(
            mode="admit", pg0=self.pg0, config=self.config, output=self.output,
            raw_root=self.raw, receipt=root / "phase-receipt.json",
            config_sha256="pin", campaign_source_sha256="pin",
            max_raw_bytes=1000, max_output_bytes=1000,
            min_raw_available_bytes=0, min_output_available_bytes=0,
            min_root_available_bytes=0, min_memory_available_bytes=0,
            max_wall_seconds=60, poll_seconds=1)
        self.safe = {"raw_added_bytes": 0, "output_allocated_bytes": 0,
                     "raw_available_bytes": 2000, "output_available_bytes": 2000,
                     "root_available_bytes": 2000, "memory_available_bytes": 2000}

    def test_admission_does_not_create_checkpoint(self):
        class Done:
            def __init__(inner, command, **kwargs):
                self.assertEqual("--admit-only", command[-1])
                (self.output / "recording-admission.json").write_text("{}")

            def poll(inner): return 0
            def wait(inner): return 0

        with (patch.object(phase, "_require_pg0_read_only"),
              patch.object(phase, "_require_local", side_effect=lambda p, *_: p),
              patch.object(phase.campaign, "_validate_config"),
              patch.object(phase, "_sha", return_value="pin"),
              patch.object(phase, "_sample", return_value=self.safe),
              patch.object(phase.subprocess, "Popen", side_effect=Done)):
            receipt = phase.run(self.args)
        self.assertEqual("accepted", receipt["status"])
        self.assertFalse((self.output / "checkpoint.json").exists())

    def test_import_needs_cached_admission_before_child(self):
        self.args.mode = "import"
        with (patch.object(phase, "_require_pg0_read_only"),
              patch.object(phase, "_require_local", side_effect=lambda p, *_: p),
              patch.object(phase.campaign, "_validate_config"),
              patch.object(phase, "_sha", return_value="pin"),
              patch.object(phase.subprocess, "Popen") as popen):
            with self.assertRaisesRegex(ValueError, "sealed recording admission"):
                phase.run(self.args)
            popen.assert_not_called()

    def test_import_creates_only_pinned_checkpoint(self):
        self.args.mode = "import"
        (self.output / "recording-admission.json").write_text("{}")

        class Done:
            def __init__(inner, command, **kwargs):
                self.assertEqual("--import-only", command[-1])
                receipt = {"source_kind": "bounded_prefix_snapshot_v1",
                           "source_completed_fault_trials": 16}
                (self.output / "predecessor-import.json").write_text(json.dumps(receipt))
                (self.output / "checkpoint.json").write_text(json.dumps({
                    "case_id": "SUCCESSOR", "healthy": None, "trials": [], "active": None,
                    "completed_fault_trials": 0, "imported_completed_fault_trials": 16,
                    "predecessor_import": receipt}))

            def poll(inner): return 0
            def wait(inner): return 0

        with (patch.object(phase, "_require_pg0_read_only"),
              patch.object(phase, "_require_local", side_effect=lambda p, *_: p),
              patch.object(phase.campaign, "_validate_config"),
              patch.object(phase, "_sha", return_value="pin"),
              patch.object(phase, "_sample", return_value=self.safe),
              patch.object(phase.subprocess, "Popen", side_effect=Done)):
            receipt = phase.run(self.args)
        self.assertEqual("accepted", receipt["status"])
        self.assertEqual(0, json.loads((self.output / "checkpoint.json").read_text())[
            "completed_fault_trials"])


if __name__ == "__main__":
    unittest.main()
