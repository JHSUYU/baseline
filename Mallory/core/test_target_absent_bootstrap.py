"""Offline contracts for bounded target discovery from observed I/O doors."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .audit import audit_campaign
from .campaign import _apply_result, _fresh_state, run, validate_config
from .events import Trace
from .feedback import analyze
from .scheduler import mutate, sequence_signature


CHECK = "pkg.Target#run()V@10:branch:1"
THROW = "pkg.Target#run()V@11:throw:1"
DOOR_A = "pkg.IO#first()V@1:door:1"
DOOR_B = "pkg.IO#second()V@2:door:1"
HASH = "a" * 64


FAKE_WORKLOAD = '''import json, os
from pathlib import Path
plan = json.loads(Path(os.environ["MALLORY_PLAN_FILE"]).read_text())["faults"]
count = Path("count")
count.write_text(str(1 + (int(count.read_text()) if count.exists() else 0)))
rows = [dict(type=kind, site=site, class_name="pkg.Target",
             bytecode_sha256="a" * 64, class_loader_id="Loader@1")
        for kind, site in (("TARGET_CHECK", "pkg.Target#run()V@10:branch:1"),
                           ("TARGET_THROW", "pkg.Target#run()V@11:throw:1"))]
Path(os.environ["MALLORY_SITE_CATALOG"]).write_text(
    "".join(json.dumps(row) + "\\n" for row in rows))
events = []
def emit(kind, seq, node, occurrence, **fields):
    events.append(dict(type=kind, id="e" + str(seq), seq=seq, node=node,
                       epoch=0, occurrence=occurrence, region=occurrence, **fields))
def receipt(kind, seq, fault):
    point = fault["point"]
    emit(kind, seq, point["node"], "first" if seq <= 3 else "second",
         fault_id=fault["fault_id"], site=point["site"],
         door_ordinal=point["door_ordinal"])
if os.environ.get("SHOW_DOORS", "1") == "1":
    emit("DOOR_OBSERVED", 1, "A", "first", site="pkg.IO#first()V@1:door:1",
         door_ordinal=1, fault_type="EXCEPTION", exception_class="java.io.IOException")
if plan:
    receipt("FAULT_MATCHED", 2, plan[0])
    receipt("FAULT_APPLIED", 3, plan[0])
if os.environ.get("SHOW_DOORS", "1") == "1":
    emit("DOOR_OBSERVED", 4, "B", "second", site="pkg.IO#second()V@2:door:1",
         door_ordinal=1, fault_type="EXCEPTION", exception_class="java.io.IOException")
if len(plan) > 1:
    receipt("FAULT_MATCHED", 5, plan[1])
    receipt("FAULT_APPLIED", 6, plan[1])
if os.environ.get("SHOW_TARGET", "1") == "early" and plan or (
        os.environ.get("SHOW_TARGET", "1") == "1" and len(plan) > 1):
    emit("TARGET_CHECK", 7, "B", "second",
         site="pkg.Target#run()V@10:branch:1")
    if len(plan) > 1:
        emit("TARGET_THROW", 8, "B", "second",
             site="pkg.Target#run()V@11:throw:1",
             exception_class="java.io.IOException")
Path(os.environ["MALLORY_EVENT_FILE"]).write_text(
    "".join(json.dumps(event) + "\\n" for event in events))
'''


def passed_junit(*_args):
    return {"status": "passed", "tests": 1, "failures": 0,
            "errors": 0, "skipped": 0}


class TargetAbsentBootstrapTest(unittest.TestCase):
    def config(self, root: Path, *, show_target: bool | str = True) -> dict:
        script = root / "fake_workload.py"
        script.write_text(FAKE_WORKLOAD, encoding="utf-8")
        return {"case_id": "TEST-BOOTSTRAP", "system": "solr",
                "cluster_test": "ExistingClusterTest#testScenario",
                "cwd": str(root), "command": [sys.executable, str(script)],
                "env": {"SHOW_TARGET": (show_target if isinstance(show_target, str)
                                         else "1" if show_target else "0")},
                "target": {"check_sites": [CHECK], "throw_site": THROW,
                           "exception_class": "java.io.IOException"},
                "expected_target_class_sha256": HASH,
                "auto_promote_if_healthy": True,
                "budget": {"trials": 2, "seconds": 30,
                           "max_faults_per_trial": 3, "trial_timeout_seconds": 5},
                "fault_types": ["EXCEPTION"], "candidate_replays": 0,
                "target_absent_bootstrap": {"door_sites": [DOOR_A, DOOR_B],
                                            "max_trials": 2,
                                            "max_doors_per_trial": 1,
                                            "max_faults_per_trial": 2}}

    def test_config_requires_exact_bounded_policy_and_pinned_class(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            validate_config(config)
            invalid = [
                {"door_sites": [], "max_trials": 2, "max_doors_per_trial": 1,
                 "max_faults_per_trial": 2},
                {"door_sites": [DOOR_A, DOOR_A], "max_trials": 2,
                 "max_doors_per_trial": 1, "max_faults_per_trial": 2},
                {"door_sites": [DOOR_A], "max_trials": 0,
                 "max_doors_per_trial": 1, "max_faults_per_trial": 2},
            ]
            for policy in invalid:
                with self.subTest(policy=policy), self.assertRaises(ValueError):
                    validate_config({**config, "target_absent_bootstrap": policy})
            with self.assertRaises(ValueError):
                validate_config({**config, "expected_target_class_sha256": "unpinned"})
            with self.assertRaises(ValueError):
                validate_config({**config, "target_absent_bootstrap": {
                    **config["target_absent_bootstrap"], "max_trials": 1}})

    def test_bootstrap_mutation_requires_effective_parent_and_never_invents_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            doors = [{"site": DOOR_A, "event_seq": 1,
                      "point": {"site": DOOR_A, "node": "A", "epoch": 0,
                                "door_ordinal": 1},
                      "fault_type": "EXCEPTION",
                      "exception_class": "java.io.IOException", "in_closure": False},
                     {"site": "unlisted", "event_seq": 2,
                      "point": {"site": "unlisted", "node": "A", "epoch": 0,
                                "door_ordinal": 1},
                      "fault_type": "EXCEPTION",
                      "exception_class": "java.io.IOException", "in_closure": False}]
            feedback = {"doors": doors, "last_fault_seq": -1,
                        "target_reached": False, "all_faults_effective": False}
            seed = mutate([], feedback, config, bootstrap=True)
            self.assertEqual(len(seed), 1)
            self.assertEqual(seed[0]["selection_reason"], "bootstrap_io")
            self.assertEqual(seed[0]["faults"][0]["point"]["site"], DOOR_A)
            self.assertEqual(mutate(seed[0]["faults"], feedback, config, bootstrap=True), [])
            feedback["all_faults_effective"] = True
            feedback["last_fault_seq"] = 1
            self.assertEqual(mutate(seed[0]["faults"], feedback, config, bootstrap=True), [])

    def test_unnamed_guard_cannot_bind_from_separately_named_throw(self):
        point = {"site": DOOR_A, "node": "A", "epoch": 0, "door_ordinal": 1}
        plan = [{"fault_id": "f1", "point": point, "fault_type": "EXCEPTION",
                 "exception_class": "java.io.IOException"}]
        def event(kind, seq, node, occurrence, **fields):
            return {"type": kind, "id": f"e{seq}", "seq": seq, "node": node,
                    "epoch": 0, "occurrence": occurrence, "region": occurrence,
                    **fields}
        events = (event("DOOR_OBSERVED", 1, "A", "io", site=DOOR_A,
                        door_ordinal=1),
                  event("FAULT_MATCHED", 2, "A", "io", fault_id="f1",
                        site=DOOR_A, door_ordinal=1),
                  event("FAULT_APPLIED", 3, "A", "io", fault_id="f1",
                        site=DOOR_A, door_ordinal=1),
                  event("TARGET_CHECK", 4, "unknown", "guard", site=CHECK),
                  event("TARGET_THROW", 5, "B", "throw", site=THROW,
                        exception_class="java.io.IOException"))
        feedback = analyze(Trace(events), {"check_sites": [CHECK],
                                           "throw_site": THROW,
                                           "exception_class": "java.io.IOException"},
                           plan, return_code=0, timed_out=False,
                           bootstrap_without_target=True)
        self.assertTrue(feedback["target_check_reached"])
        self.assertEqual(feedback["target_check_actors"], [])
        self.assertFalse(feedback["target_exception_candidate"])

    def test_discovers_exact_target_after_two_faults_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            path = root / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            out = root / "campaign"
            with patch("Mallory.core.campaign.collect_junit_receipt", side_effect=passed_junit):
                state = run(path, out)
                self.assertEqual(run(path, out)["completed_trials"], [0, 1, 2])
            self.assertEqual(state["status"], "budget_exhausted")
            self.assertEqual((root / "count").read_text(), "3")
            self.assertEqual(state["target_discovered_trial"], 2)
            self.assertEqual(state["target_binding"], {"nodes": ["B"]})
            self.assertEqual(state["bootstrap_fault_trials"], 2)
            self.assertTrue(state["runtime_attestation"]["valid"])
            self.assertFalse(state["runtime_attestation"]["target_closure_proven"])
            healthy = json.loads((out / "trials/r0000/result.json").read_text())
            first = json.loads((out / "trials/r0001/result.json").read_text())
            second = json.loads((out / "trials/r0002/result.json").read_text())
            self.assertEqual(healthy["feedback"]["graph"]["analysis_skipped"],
                             "healthy_target_absent")
            self.assertEqual(first["feedback"]["graph"]["analysis_skipped"],
                             "bootstrap_target_absent")
            self.assertEqual(healthy["feedback"]["closure_occurrences"], [])
            self.assertEqual(first["feedback"]["closure_occurrences"], [])
            self.assertNotIn("analysis_skipped", second["feedback"]["graph"])
            self.assertTrue(second["feedback"]["target_exception_candidate"])
            self.assertEqual([row["selection_reason"] for row in (first, second)],
                             ["bootstrap_io", "bootstrap_io"])
            summary = json.loads((out / "result.json").read_text())
            self.assertFalse(summary["healthy_seed_valid"])
            self.assertTrue(summary["bootstrap_seed_valid"])
            self.assertEqual(summary["target_discovered_trial"], 2)
            self.assertEqual(summary["exact_exception_trials"], 1)
            audit = audit_campaign(out, root / "audit.json")
            self.assertTrue(audit["archive_integrity_valid"])
            self.assertTrue(audit["guidance_consistent"])
            self.assertTrue(audit["target_claims_reverified"])
            self.assertFalse(audit["healthy_closure_proven"])
            self.assertFalse(audit["report_gate_passed"])

    def test_bootstrap_limit_and_missing_door_are_terminal_without_false_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root, show_target=False)
            config["target_absent_bootstrap"]["max_trials"] = 3
            config["target_absent_bootstrap"]["max_doors_per_trial"] = 2
            config["budget"]["trials"] = 3
            path = root / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch("Mallory.core.campaign.collect_junit_receipt", side_effect=passed_junit):
                state = run(path, root / "limited")
            self.assertEqual(state["status"], "budget_exhausted")
            self.assertEqual(state["completed_trials"], [0, 1, 2, 3])
            self.assertIsNone(state["target_binding"] if "target_binding" in state else None)
            self.assertEqual((root / "count").read_text(), "4")
            config["target_absent_bootstrap"]["door_sites"] = ["absent#door"]
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch("Mallory.core.campaign.collect_junit_receipt", side_effect=passed_junit):
                missing = run(path, root / "missing")
            self.assertEqual(missing["status"], "healthy_bootstrap_attestation_failed")
            self.assertEqual(missing["completed_trials"], [0])
            self.assertIn("no_named_configured_io_door",
                          missing["runtime_attestation"]["reasons"])
            config["target_absent_bootstrap"]["door_sites"] = [DOOR_A, DOOR_B]
            config["env"]["SHOW_DOORS"] = "0"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch("Mallory.core.campaign.collect_junit_receipt", side_effect=passed_junit):
                zero_door = run(path, root / "zero_doors")
            self.assertEqual(zero_door["status"], "healthy_bootstrap_attestation_failed")
            self.assertEqual(zero_door["completed_trials"], [0])
            self.assertEqual(zero_door["bootstrap_seed_doors"], 0)

    def test_real_target_graph_replaces_bootstrap_queue_after_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root, show_target="early")
            path = root / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch("Mallory.core.campaign.collect_junit_receipt", side_effect=passed_junit):
                state = run(path, root / "campaign")
            self.assertEqual(state["target_discovered_trial"], 1)
            self.assertEqual(state["target_binding_trial"], 1)
            first = json.loads((root / "campaign/trials/r0001/result.json").read_text())
            second = json.loads((root / "campaign/trials/r0002/result.json").read_text())
            self.assertIn("second", first["feedback"]["closure_occurrences"][0])
            self.assertEqual(second["selection_reason"], "dynamic_closure")
            self.assertTrue(second["feedback"]["target_exception_candidate"])
            audit = audit_campaign(root / "campaign", root / "audit.json")
            self.assertTrue(audit["guidance_consistent"])
            self.assertTrue(audit["target_claims_reverified"])

    def test_discarded_bootstrap_signature_can_be_readmitted_by_real_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            first = {"fault_id": "f1", "point": {"site": DOOR_A, "node": "A",
                                                  "epoch": 0, "door_ordinal": 1},
                     "fault_type": "EXCEPTION", "exception_class": "java.io.IOException"}
            second = {"fault_id": "f2", "point": {"site": DOOR_B, "node": "B",
                                                   "epoch": 0, "door_ordinal": 1},
                      "fault_type": "EXCEPTION", "exception_class": "java.io.IOException"}
            signature = sequence_signature([first, second])
            state = _fresh_state(config)
            state["out"] = str(root)
            state["completed_trials"] = [0]
            state["queue"] = [{"faults": [first, second], "signature": signature,
                               "selection_reason": "bootstrap_io", "priority": 1,
                               "queued_at": 0}]
            state["seen_sequences"] = [signature]
            feedback = {"status": "observed", "all_faults_effective": True,
                        "target_reached": True, "target_check_reached": True,
                        "target_identity_complete": True,
                        "target_region_present": True,
                        "target_check_actors": ["B"],
                        "target_exception_candidate": False,
                        "coverage_ids": [], "closure_coverage_ids": [],
                        "closure_edges": [], "last_fault_seq": 3,
                        "doors": [{"site": DOOR_B, "event_seq": 4,
                                   "point": second["point"],
                                   "fault_type": "EXCEPTION",
                                   "exception_class": "java.io.IOException",
                                   "in_closure": True}]}
            _apply_result(state, config, {"trial_id": 1, "elapsed_seconds": 1.0,
                                          "plan": [first], "feedback": feedback},
                          {"faults": [first], "selection_reason": "bootstrap_io"})
            self.assertEqual(state["target_binding"], {"nodes": ["B"]})
            self.assertEqual([item["signature"] for item in state["queue"]], [signature])
            self.assertEqual(state["queue"][0]["selection_reason"], "dynamic_closure")


if __name__ == "__main__":
    unittest.main()
