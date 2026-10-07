#!/usr/bin/env python3
"""Checkpoint scheduler tests using exact fault results, not a mocked score."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from campaign import select_next, suffix_family, suffix_feedback


SITE = "SaslDataTransferServer.doSaslHandshake#readSecret"
MAGIC = "SaslDataTransferServer.doSaslHandshake#readMagic"


def item(identity, ordinal, priority, enqueued=1.0):
    return {
        "id": identity, "priority": priority, "enqueued": enqueued,
        "sequence": [
            {"siteId": MAGIC, "actorLocalOrdinal": 1,
             "faultActor": "actor", "resource": "BP0"},
            {"siteId": SITE, "actorLocalOrdinal": ordinal,
             "faultActor": "actor", "resource": "BP0"},
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
        plan.write_text(f"FAULT\t{MAGIC}\tactor\tBP0\t1\tIOException\n"
                        f"FAULT\t{SITE}\tactor\tBP0\t{ordinal}\tIOException\n")

    def test_repeated_exact_target_loss_demotes_suffix(self):
        with TemporaryDirectory() as name:
            output = Path(name)
            for index in range(3):
                self.result(output, f"lost-{index}", 2)
            state = {"completed": {f"lost-{i}": {} for i in range(3)},
                     "in_flight": None, "attempted_trials": 3,
                     "queue": [item("demoted", 2, 500), item("fresh", 3, 100)]}
            self.assertEqual(suffix_feedback(output, state)[suffix_family(item("probe", 2, 0)["sequence"])],
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

    def test_three_fault_recovery_does_not_cancel_two_fault_loss(self):
        with TemporaryDirectory() as name:
            output = Path(name)
            for index in range(3):
                self.result(output, f"lost-{index}", 2)
            run = output / "runs" / "valid-three"
            plan = output / "plans" / "valid-three.tsv"
            run.mkdir(parents=True)
            (run / "v2_result.json").write_text(json.dumps({
                "exact_order_applied": True, "valid_for_feedback": True,
            }))
            plan.write_text("FAULT\tmagic\tactor\tBP0\t1\tIOException\n"
                            "FAULT\toptions\tactor\tBP0\t1\tIOException\n"
                            f"FAULT\t{SITE}\tactor\tBP0\t2\tIOException\n")
            state = {"completed": {**{f"lost-{i}": {} for i in range(3)},
                                   "valid-three": {}},
                     "in_flight": None, "attempted_trials": 4,
                     "queue": [item("demoted", 2, 500), item("fresh", 3, 100)]}
            selected, _ = select_next(output, state)
            self.assertEqual(selected["id"], "fresh")
            feedback = suffix_feedback(output, state)
            self.assertEqual(feedback[suffix_family(item("probe", 2, 0)["sequence"])],
                             {"lost": 3, "valid": 0})


if __name__ == "__main__":
    unittest.main()
