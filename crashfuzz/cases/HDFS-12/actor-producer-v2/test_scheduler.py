#!/usr/bin/env python3
"""Checkpoint scheduler tests using exact fault results, not a mocked score."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from campaign import (initial_state, parent_prefix_feedback, parent_prefix_key,
                      plan_text, select_next, suffix_family, suffix_feedback)
from identity_gate import KEYS


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
    def test_initial_io_feedback_uses_both_healthy_calibrations(self):
        with TemporaryDirectory() as name:
            output = Path(name)
            a, b = output / "healthy-a", output / "healthy-b"
            a.mkdir()
            b.mkdir()
            first = {"event": "FAULT_POINT_OBSERVED",
                     "marker": "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE",
                     "siteId": "BPServiceActor.offerService#keyUpdateResponse/NN0",
                     "sourceKey": "dn1/BP0", "occurrence": "dn1/BP0/NN0",
                     "hitOrdinal": 1, "actorLocalOrdinal": 1,
                     "faultActor": "dn1", "resource": "BP0",
                     "keyRole": "ROTATED_CURRENT"}
            second = dict(first, siteId="BPOfferService.processCommand#applyKeys/NN0",
                          marker="FAULT:HDFS_KEY_UPDATE:LOCAL_APPLY")
            (a / "runtime_trace.jsonl").write_text(json.dumps(first) + "\n")
            (b / "runtime_trace.jsonl").write_text(json.dumps(second) + "\n")
            state = initial_state("HDFS-12", output, {
                "stable_selectors": [[first[key] for key in KEYS]],
            })
            self.assertEqual(len(state["io_families"]), 2)
            self.assertTrue(any("LOCAL_APPLY" in family
                                for family in state["io_families"]))

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

    def test_partial_children_demote_only_their_exact_parent_prefix(self):
        def step(site, ordinal, fault_type="IOException"):
            return {"marker": "FAULT:HDFS_SASL:READ", "siteId": site,
                    "faultActor": "dn1", "resource": "BP0",
                    "hitOrdinal": ordinal, "actorLocalOrdinal": ordinal,
                    "faultType": fault_type, "requiredRawKeyId": "-"}

        with TemporaryDirectory() as name:
            output = Path(name)
            (output / "runs").mkdir()
            (output / "plans").mkdir()
            bad_parent = [step("response", 1), step("readMagic", 2),
                          step("readSecret", 3)]
            good_parent = [step("response", 1), step("readOptions", 2),
                           step("readSecret", 3)]
            for index, fault_type in enumerate(
                    ("IOException", "EOFException", "SocketTimeoutException")):
                identity = f"lost-child-{index}"
                (output / "runs" / identity).mkdir()
                (output / "runs" / identity / "v2_result.json").write_text(
                    json.dumps({"valid_for_feedback": False,
                                "exact_order_applied": False}))
                (output / "plans" / (identity + ".tsv")).write_text(
                    plan_text(bad_parent + [step("later", 4, fault_type)]))
            state = {"completed": {f"lost-child-{i}": {} for i in range(3)},
                     "in_flight": None, "attempted_trials": 3,
                     "queue": [
                         {"id": "bad", "priority": 500, "enqueued": 1.0,
                          "sequence": bad_parent + [step("later", 4)]},
                         {"id": "good", "priority": 100, "enqueued": 1.0,
                          "sequence": good_parent + [step("later", 4)]},
                     ]}
            self.assertEqual(parent_prefix_feedback(output, state)
                             [parent_prefix_key(state["queue"][0]["sequence"])],
                             {"lost": 3, "valid": 0})
            chosen, _ = select_next(output, state)
            self.assertEqual(chosen["id"], "good")
            identity = "valid-child"
            (output / "runs" / identity).mkdir()
            (output / "runs" / identity / "v2_result.json").write_text(
                json.dumps({"valid_for_feedback": True,
                            "exact_order_applied": True}))
            (output / "plans" / (identity + ".tsv")).write_text(
                plan_text(bad_parent + [step("other", 4)]))
            state["completed"][identity] = {}
            state["attempted_trials"] = 4
            chosen, receipt = select_next(output, state)
            self.assertEqual(chosen["id"], "bad")
            self.assertEqual(receipt["parent_target_loss_penalty"], 0)


if __name__ == "__main__":
    unittest.main()
