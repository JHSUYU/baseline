#!/usr/bin/env python3
"""Prove the pinned JUnit gate recognizes the future v3 wrapper."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"
V2_RAW = ROOT / "data/mallory/calibration_solr40_reference_handoff_v2_node0/SOLR-40"
sys.path.insert(0, str(PINNED))
from Mallory.core.junit import collect_junit_receipt, runner_kind  # noqa: E402


class RunnerRecognitionTests(unittest.TestCase):
    def test_exact_pinned_runner_basename(self) -> None:
        config = json.loads((HERE / "config.json").read_text())
        self.assertEqual(runner_kind(config["command"]), "solr_junit_wrapper")
        old = str(HERE.parent / "healthy-watcher-handoff-node0-v2/run_pilot_v2.py")
        old_argv = list(config["command"])
        old_argv[1] = old
        self.assertIsNone(runner_kind(old_argv))

    def test_sealed_v2_raw_receipt_passes_with_v3_argv(self) -> None:
        config = json.loads((HERE / "config.json").read_text())
        receipt = collect_junit_receipt(
            V2_RAW / "trials/r0000", config["command"], Path(config["cwd"]),
            0, None, config["cluster_test"])
        self.assertEqual(receipt["runner"], "solr_junit_wrapper")
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual((receipt["tests"], receipt["failures"], receipt["errors"],
                          receipt["skipped"]), (1, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
