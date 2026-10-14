"""Focused tests for the accepted-checkpoint one-fault capacity wrapper."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign
from Mallory.native_graphchecker_campaign import guarded_one_fault as guard


class GuardedOneFaultTest(unittest.TestCase):
    def test_pg0_mount_check_rejects_writable_nested_bind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pg0 = Path(directory)
            nested = pg0 / "nested"
            nested.mkdir()
            ro = argparse.Namespace(f_flag=os.ST_RDONLY)
            rw = argparse.Namespace(f_flag=0)
            with (patch.object(guard, "_mount_points",
                               return_value={Path("/"), pg0, nested}),
                  patch.object(guard.os, "statvfs", side_effect=lambda path:
                               rw if path == nested else ro)):
                with self.assertRaisesRegex(ValueError, "writable mount"):
                    guard._require_pg0_read_only(pg0)
            with (patch.object(guard, "_mount_points",
                               return_value={Path("/"), pg0, nested}),
                  patch.object(guard.os, "statvfs", return_value=ro)):
                guard._require_pg0_read_only(pg0)

    def test_capacity_classifies_raw_growth_and_floor(self) -> None:
        limits = argparse.Namespace(max_raw_bytes=500, max_output_bytes=1000,
                                    min_raw_available_bytes=100,
                                    min_output_available_bytes=100,
                                    min_memory_available_bytes=100)
        sample = {"raw_added_bytes": 500, "output_allocated_bytes": 5,
                  "raw_available_bytes": 10000,
                  "output_available_bytes": 10000,
                  "memory_available_bytes": 10000}
        self.assertEqual("raw_cap", guard._breach(sample, limits))
        sample["raw_added_bytes"] = 499
        sample["raw_available_bytes"] = 100
        self.assertEqual("raw_free_floor", guard._breach(sample, limits))

    def _args(self, pg0: Path, config: Path, output: Path, raw: Path) -> argparse.Namespace:
        return argparse.Namespace(pg0=pg0, config=config, output=output,
                                  raw_root=raw, attempt_id="trial-0004",
                                  config_sha256=guard._sha(config),
                                  campaign_source_sha256=guard._sha(
                                      Path(campaign.__file__)),
                                  max_raw_bytes=1000000,
                                  max_output_bytes=1000000,
                                  min_raw_available_bytes=0,
                                  min_output_available_bytes=0,
                                  min_memory_available_bytes=0,
                                  max_wall_seconds=60, poll_seconds=0.01)

    def test_same_intent_cannot_run_second_accepted_fault(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pg0, output, raw = (root / name for name in ("pg0", "output", "raw"))
            for path in (pg0, output, raw):
                path.mkdir()
            config = root / "config.json"
            config.write_text(json.dumps({"case_id": "CASE", "budget": {
                "fault_trials": 8}, "runner": {"local_artifact_root": str(raw)}}))
            args = self._args(pg0, config, output, raw)

            class CompletedChild:
                pid = 1

                def __init__(self, *unused, **kwargs):
                    self.command = unused[0]
                    self.returncode = 0
                    campaign._atomic(output / "checkpoint.json", {
                        "completed_fault_trials": 1, "active": None,
                        "terminal": False})

                def poll(self):
                    return 0

                def wait(self):
                    return 0

            safe_sample = {"raw_added_bytes": 0, "output_allocated_bytes": 0,
                           "raw_available_bytes": 10000000,
                           "output_available_bytes": 10000000,
                           "memory_available_bytes": 10000000}
            with (patch.object(guard, "_require_pg0_read_only"),
                  patch.object(guard, "_require_local", side_effect=lambda path, *_:
                               path.resolve()),
                  patch.object(campaign, "_validate_config"),
                  patch.object(guard, "_sample", return_value=safe_sample),
                  patch.object(guard.subprocess, "Popen", side_effect=CompletedChild)
                  as popen):
                first = guard.run_one(args)
                self.assertEqual("accepted_one", first["status"])
                self.assertEqual(1, first["completed_fault_trials"])
                self.assertIn("--stop-after-fault-trials", popen.call_args.args[0])
                second = guard.run_one(args)
                self.assertEqual("already_completed", second["status"])
                self.assertEqual(1, popen.call_count)
                args.max_raw_bytes += 1
                with self.assertRaisesRegex(ValueError, "intent pins changed"):
                    guard.run_one(args)

    def test_capacity_refusal_happens_before_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pg0, output, raw = (root / name for name in ("pg0", "output", "raw"))
            for path in (pg0, output, raw):
                path.mkdir()
            config = root / "config.json"
            config.write_text(json.dumps({"case_id": "CASE", "budget": {
                "fault_trials": 8}, "runner": {"local_artifact_root": str(raw)}}))
            args = self._args(pg0, config, output, raw)
            over_cap = {"raw_added_bytes": args.max_raw_bytes,
                        "output_allocated_bytes": 0,
                        "raw_available_bytes": 10000000,
                        "output_available_bytes": 10000000,
                        "memory_available_bytes": 10000000}
            with (patch.object(guard, "_require_pg0_read_only"),
                  patch.object(guard, "_require_local", side_effect=lambda path, *_:
                               path.resolve()),
                  patch.object(campaign, "_validate_config"),
                  patch.object(guard, "_sample", return_value=over_cap),
                  patch.object(guard.subprocess, "Popen") as popen):
                with self.assertRaisesRegex(RuntimeError, "raw_cap"):
                    guard.run_one(args)
                popen.assert_not_called()

    def test_running_raw_cap_stops_child_without_accepting_fault(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pg0, output, raw = (root / name for name in ("pg0", "output", "raw"))
            for path in (pg0, output, raw):
                path.mkdir()
            config = root / "config.json"
            config.write_text(json.dumps({"case_id": "CASE", "budget": {
                "fault_trials": 8}, "runner": {"local_artifact_root": str(raw)}}))
            args = self._args(pg0, config, output, raw)
            safe = {"raw_added_bytes": 0, "output_allocated_bytes": 0,
                    "raw_available_bytes": 10000000,
                    "output_available_bytes": 10000000,
                    "memory_available_bytes": 10000000}
            over_cap = {**safe, "raw_added_bytes": args.max_raw_bytes}

            class RunningChild:
                pid = 1
                returncode = None

                def poll(self):
                    return self.returncode

                def wait(self):
                    return self.returncode

            child = RunningChild()

            def stop(process):
                self.assertIs(process, child)
                process.returncode = 143

            with (patch.object(guard, "_require_pg0_read_only"),
                  patch.object(guard, "_require_local", side_effect=lambda path, *_:
                               path.resolve()),
                  patch.object(campaign, "_validate_config"),
                  patch.object(guard, "_sample",
                               side_effect=[safe, over_cap, over_cap]),
                  patch.object(guard.subprocess, "Popen", return_value=child),
                  patch.object(guard, "_stop_group", side_effect=stop) as stopped):
                receipt = guard.run_one(args)
            stopped.assert_called_once()
            self.assertEqual("guard_stop", receipt["status"])
            self.assertEqual("raw_cap", receipt["guard_reason"])
            self.assertEqual(0, receipt["completed_fault_trials"])


if __name__ == "__main__":
    unittest.main()
