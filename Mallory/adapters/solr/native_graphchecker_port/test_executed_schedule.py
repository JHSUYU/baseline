"""Solr preparation reuses only successful, source-pinned original commands."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from Mallory.adapters.solr.native_graphchecker_port import prepare_case as prep
from Mallory.native_graphchecker_campaign import campaign as native
from Mallory.native_graphchecker_campaign import record_command


class ExecutedScheduleTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.healthy = self.root / "healthy"
        self.trace = self.healthy / "trace"
        self.scheduled = self.healthy / "scheduled"
        self.trace.mkdir(parents=True)
        self.scheduled.mkdir()
        self.script = self.root / "run_original_recorder_scheduler.sh"
        self.script.write_text("#!/bin/sh\n# original Solr GraphChecker commands\n")
        self.index = self.scheduled / "runtime_workflow_schedule_index.json"
        self.plan = self.scheduled / "execution_task_plan.jsonl"
        self.index.write_text("{}\n")
        self.plan.write_text('{"taskId":"one"}\n')
        self.jar = self.root / "engine.jar"
        self.jar.write_bytes(b"engine")
        self.config = {"recording": {}}

    def _record(self, stage: str) -> Path:
        receipt = self.healthy / f"{stage}-command.json"
        subprocess.run([sys.executable, str(Path(record_command.__file__)),
                        "--script", str(self.script), "--receipt", str(receipt),
                        "--stdout", str(self.healthy / f"{stage}.stdout.log"),
                        "--stderr", str(self.healthy / f"{stage}.stderr.log"),
                        "--", sys.executable, "-c", f"print({stage!r})"], check=True)
        return receipt

    def _bind(self) -> bool:
        with patch.object(native, "JAR", self.jar), patch.object(
                native, "seal_precomputed_schedule") as seal:
            result = prep.bind_executed_schedule(
                self.config, self.trace, self.index, self.plan, self.jar)
            if result:
                seal.assert_called_once()
            else:
                seal.assert_not_called()
            return result

    def test_reuses_only_two_executed_source_pinned_commands(self) -> None:
        self.assertFalse(self._bind())
        self._record("recorder")
        with self.assertRaises(FileNotFoundError):
            self._bind()
        self._record("scheduler")
        self.assertTrue(self._bind())
        self.assertEqual(self.config["recording"]["precomputed_schedule"],
                         str(self.healthy / "precomputed-schedule.json"))
        self.script.write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            self._bind()

    def test_mutated_receipt_or_output_fails_closed(self) -> None:
        recorder = self._record("recorder")
        self._record("scheduler")
        evidence = json.loads(recorder.read_text())
        evidence["returncode"] = 1
        recorder.write_text(json.dumps(evidence))
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            self._bind()
        evidence["returncode"] = 0
        recorder.write_text(json.dumps(evidence))
        (self.healthy / "recorder.stdout.log").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            self._bind()

    def test_nonzero_command_leaves_no_reusable_receipt(self) -> None:
        receipt = self._record("recorder")
        with self.assertRaises(Exception):
            record_command.run(self.script, receipt,
                               self.healthy / "recorder.stdout.log",
                               self.healthy / "recorder.stderr.log",
                               [sys.executable, "-c", "raise SystemExit(1)"])
        self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
