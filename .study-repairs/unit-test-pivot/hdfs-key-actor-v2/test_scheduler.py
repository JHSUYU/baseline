#!/usr/bin/env python3
"""Checkpoint scheduler tests using exact fault results, not a mocked score."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from campaign import select_next, suffix_feedback


SITE = "SaslDataTransferServer.doSaslHandshake#readSecret"


def item(identity, ordinal, priority, enqueued=1.0):
    return {
        "id": identity, "priority": priority, "enqueued": enqueued,
        "sequence": [
            {"siteId": "SaslDataTransferServer.doSaslHandshake#readMagic",
             "actorLocalOrdinal": 1},
            {"siteId": SITE, "actorLocalOrdinal": ordinal},
        ],
    }


class SchedulerTests(unittest.TestCase):
    def result(self, output: Path, identity: str, ordinal: int,
               *, exact=True, valid=False):
        run = output / "runs" / identity
        plan = output / "plans" / (identity + ".tsv")
        run.mkdir(parents=True)
        plan.parent.mkdir(parents=True, exist_ok=True)
        (run / "v2_result.json").write_text(json.dumps({
            "exact_order_applied": exact, "valid_for_feedback": valid,
        }))
        plan.write_text("FAULT\tmagic\tactor\tBP0\t1\tIOException\n"
                        f"FAULT\t{SITE}\tactor\tBP0\t{ordinal}\tIOException\n")

    def test_repeated_exact_target_loss_demotes_suffix(self):
        with TemporaryDirectory() as name:
            output = Path(name)
            for index in range(3):
                self.result(output, f"lost-{index}", 2)
            state = {"completed": {f"lost-{i}": {} for i in range(3)},
                     "in_flight": None, "attempted_trials": 3,
                     "queue": [item("demoted", 2, 500), item("fresh", 3, 100)]}
            self.assertEqual(suffix_feedback(output, state)[SITE + "|actorOrdinal=2"],
                             {"lost": 3, "valid": 0})
            selected, receipt = select_next(output, state)
            self.assertEqual(selected["id"], "fresh")
            self.assertEqual(receipt["target_loss_penalty"], 0)

    def test_valid_result_or_unmatched_fault_cannot_create_demote(self):
        with TemporaryDirectory() as name:
            output = Path(name)
            self.result(output, "valid", 2, valid=True)
            for index in range(3):
                self.result(output, f"unmatched-{index}", 2, exact=False)
            state = {"completed": {x: {} for x in
                                   ["valid", *(f"unmatched-{i}" for i in range(3))]},
                     "in_flight": None, "attempted_trials": 4,
                     "queue": [item("preferred", 2, 500), item("other", 3, 100)]}
            selected, receipt = select_next(output, state)
            self.assertEqual(selected["id"], "preferred")
            self.assertEqual(receipt["prior_valid"], 1)
            self.assertEqual(receipt["target_loss_penalty"], 0)

    def test_exploration_and_inflight_resume(self):
        with TemporaryDirectory() as name:
            output = Path(name)
            for index in range(3):
                self.result(output, f"lost-{index}", 2)
            state = {"completed": {f"lost-{i}": {} for i in range(3)},
                     "in_flight": None, "attempted_trials": 11,
                     "queue": [item("demoted", 2, 500), item("fresh", 3, 100)]}
            selected, receipt = select_next(output, state)
            self.assertEqual(selected["id"], "demoted")
            self.assertEqual(receipt["reason"], "penalized_family_exploration")
            state["in_flight"] = "fresh"
            selected, receipt = select_next(output, state)
            self.assertEqual(selected["id"], "fresh")
            self.assertEqual(receipt["reason"], "resume_in_flight")


if __name__ == "__main__":
    unittest.main()
