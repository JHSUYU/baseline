"""Focused no-JVM tests for the native healthy-only capacity wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import guarded_healthy


class GuardedHealthyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.pg0, self.output, self.raw, self.work = (
            root / name for name in ("pg0", "output", "raw", "work"))
        for path in (self.pg0, self.output, self.raw, self.work):
            path.mkdir()
        self.config = root / "config.json"
        self.config.write_text(json.dumps({
            "runner": {"local_artifact_root": str(self.raw),
                       "local_work_root": str(self.work)}}))
        self.args = argparse.Namespace(
            pg0=self.pg0, config=self.config, output=self.output,
            raw_root=self.raw, receipt=root / "receipt.json",
            config_sha256="pin", campaign_source_sha256="pin",
            max_raw_bytes=1000, max_output_bytes=1000,
            min_raw_available_bytes=0, min_output_available_bytes=0,
            min_root_available_bytes=0, min_memory_available_bytes=0,
            max_wall_seconds=60, poll_seconds=1.0)

    def test_runs_only_healthy_and_accepts_zero_fault_checkpoint(self) -> None:
        sample = {"raw_added_bytes": 0, "output_allocated_bytes": 0,
                  "raw_available_bytes": 2000, "output_available_bytes": 2000,
                  "root_available_bytes": 2000, "memory_available_bytes": 2000}

        class DoneProcess:
            def __init__(inner, command, **kwargs):
                self.assertEqual("0", command[-1])
                trial = self.output / "trials/r0000"
                trial.mkdir(parents=True)
                (trial / "result.json").write_text('{"status":"healthy_seed"}')
                (self.output / "checkpoint.json").write_text(json.dumps({
                    "completed_fault_trials": 0,
                    "healthy": {"status": "healthy_seed"}}))

            def poll(inner):
                return 0

            def wait(inner):
                return 0

        with (patch.object(guarded_healthy, "_require_pg0_read_only"),
              patch.object(guarded_healthy, "_require_local",
                           side_effect=lambda path, *_: path),
              patch.object(guarded_healthy.campaign, "_validate_config"),
              patch.object(guarded_healthy, "_sha", return_value="pin"),
              patch.object(guarded_healthy, "_sample", return_value=sample),
              patch.object(guarded_healthy.subprocess, "Popen",
                           side_effect=DoneProcess)):
            receipt = guarded_healthy.run_healthy(self.args)
        self.assertEqual("healthy_seed", receipt["status"])
        self.assertEqual(0, receipt["completed_fault_trials"])

    def test_rejects_existing_output_before_process_start(self) -> None:
        (self.output / "checkpoint.json").write_text("{}")
        with (patch.object(guarded_healthy, "_require_pg0_read_only"),
              patch.object(guarded_healthy, "_require_local",
                           side_effect=lambda path, *_: path),
              patch.object(guarded_healthy.campaign, "_validate_config"),
              patch.object(guarded_healthy, "_sha", return_value="pin"),
              patch.object(guarded_healthy.subprocess, "Popen") as popen):
            with self.assertRaisesRegex(ValueError, "fresh and empty"):
                guarded_healthy.run_healthy(self.args)
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
