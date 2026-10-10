#!/usr/bin/env python3
"""Offline admission tests using the sealed v3 healthy observations."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V3_RAW = ROOT / "data/mallory/calibration_solr40_reference_handoff_v3_node0/SOLR-40"
sys.path.insert(0, str(HERE))
from seed_gate import (digest, promote, read, validate_plan, validate_queue, validate_seed,
                       verify_promotion)  # noqa: E402


def source() -> tuple[dict, dict, dict]:
    return tuple(json.loads((V3_RAW / name).read_text()) for name in
                 ("result.json", "trials/r0000/result.json", "handoff-audit.json"))


class FreshSeedGateTests(unittest.TestCase):
    def test_sealed_v3_source_meets_gate(self) -> None:
        receipt = validate_seed(*source())
        self.assertEqual(receipt["status"], "fresh_r0000_admitted")
        self.assertEqual(receipt["named_observed_watcher_doors"], 7)
        self.assertEqual(len(receipt["exact_reference_witnesses"]), 7)

    def test_rejects_unrecognized_or_nonpassing_junit(self) -> None:
        summary, trial, audit = map(copy.deepcopy, source())
        trial["junit_validation"]["runner"] = None
        with self.assertRaisesRegex(ValueError, "fresh r0000"):
            validate_seed(summary, trial, audit)
        trial["junit_validation"]["runner"] = "solr_junit_wrapper"
        trial["junit_validation"]["failures"] = 1
        with self.assertRaisesRegex(ValueError, "fresh r0000"):
            validate_seed(summary, trial, audit)

    def test_rejects_candidate_or_missing_reference_path(self) -> None:
        summary, trial, audit = map(copy.deepcopy, source())
        for witness in audit["exact_reference_witnesses"].values():
            witness["edge_kinds"] = [kind for kind in witness["edge_kinds"]
                                     if kind != "state_ref"]
        with self.assertRaisesRegex(ValueError, "fresh r0000"):
            validate_seed(summary, trial, audit)
        audit["exact_reference_witnesses"] = {}
        with self.assertRaisesRegex(ValueError, "fresh r0000"):
            validate_seed(summary, trial, audit)

    def test_rejects_lost_or_unnamed_target(self) -> None:
        summary, trial, audit = map(copy.deepcopy, source())
        trial["feedback"]["target_reached"] = False
        with self.assertRaisesRegex(ValueError, "fresh r0000"):
            validate_seed(summary, trial, audit)
        trial["feedback"]["target_reached"] = True
        summary["target_node_named"] = False
        with self.assertRaisesRegex(ValueError, "fresh r0000"):
            validate_seed(summary, trial, audit)

    def test_queue_requires_every_exact_named_watcher_door(self) -> None:
        _, trial, audit = source()
        verdict = validate_seed(*source())
        queue = read(V3_RAW / "checkpoint.json")["queue"]
        validate_queue(queue, trial, verdict)
        with self.assertRaisesRegex(ValueError, "mutation queue"):
            validate_queue(queue[:-1], trial, verdict)
        wrong = copy.deepcopy(queue)
        wrong[0]["faults"][0]["point"]["node"] = "unknown"
        with self.assertRaisesRegex(ValueError, "mutation queue"):
            validate_queue(wrong, trial, verdict)

    def test_two_phase_promotion_and_immutable_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            (out / "trials/r0000").mkdir(parents=True)
            for name in ("result.json", "trials/r0000/result.json",
                         "trials/r0000/events.jsonl.gz", "trials/r0000/junit.log"):
                shutil.copyfile(V3_RAW / name, out / name)
            shutil.copyfile(HERE / "config.json", out / "config.json")
            config = read(out / "config.json")
            state = read(V3_RAW / "checkpoint.json")
            state["config_digest"] = digest(config)
            (out / "checkpoint.json").write_text(json.dumps(state))
            (out / ".campaign.lock").touch()
            self.assertFalse((out / "fresh-r0000-gate.json").exists())
            verdict = promote(out)
            self.assertEqual(verdict["queue_entries"], 7)
            self.assertEqual(verify_promotion(out), verdict)
            self.assertFalse(read(out / "checkpoint.json")["calibration_only"])
            plan = state["queue"][0]["faults"]
            validate_plan(out, plan)
            wrong = copy.deepcopy(plan)
            wrong[0]["point"]["node"] = "unknown"
            with self.assertRaisesRegex(ValueError, "prior observed"):
                validate_plan(out, wrong)
            with (out / "trials/r0000/junit.log").open("a") as handle:
                handle.write("tamper")
            with self.assertRaisesRegex(ValueError, "seed changed"):
                verify_promotion(out)


if __name__ == "__main__":
    unittest.main()
