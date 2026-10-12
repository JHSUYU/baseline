"""A valid fault can miss the target actor when routing changes between runs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .campaign import _apply_result, _fresh_state
from .scheduler import sequence_signature


class ActorMissReplayTest(unittest.TestCase):
    def test_target_related_fault_gets_bounded_replay_after_target_moves(self):
        fault = {"fault_id": "f0", "fault_type": "EXCEPTION",
                 "point": {"site": "AliasesManager#process:door:1", "node": "node3",
                           "epoch": 0, "door_ordinal": 1},
                 "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException"}
        plan = [fault]
        config = {"case_id": "SOLR-40", "actor_miss_replays": 1,
                  "budget": {"max_faults_per_trial": 1}}
        for selection_reason in ("dynamic_closure", "node_timeline_candidate"):
            with self.subTest(selection_reason=selection_reason):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    state = _fresh_state(config)
                    state.update({"out": str(root), "completed_trials": [0],
                                  "target_binding": {"nodes": ["node3"]}})
                    original = {"faults": plan, "signature": sequence_signature(plan),
                                "selection_reason": selection_reason, "priority": 42.0,
                                "queued_at": 0}
                    feedback = {"status": "observed", "coverage_ids": [],
                                "closure_coverage_ids": [], "closure_edges": [],
                                "all_faults_effective": True, "target_reached": True,
                                "target_check_reached": True,
                                "target_identity_complete": True,
                                "target_check_actors": ["node2"],
                                "target_exception_candidate": False}
                    for trial_id, item in ((1, original), (2, None)):
                        (root / "trials" / f"r{trial_id:04d}").mkdir(parents=True)
                        if item is None:
                            self.assertEqual(len(state["queue"]), 1)
                            item = state["queue"].pop()
                            self.assertEqual(item["selection_reason"], "actor_miss_replay")
                            self.assertEqual(item["actor_miss_replay_attempt"], 1)
                            self.assertEqual(item["actor_miss_of"], 1)
                        _apply_result(state, config,
                                      {"trial_id": trial_id, "elapsed_seconds": 1.0,
                                       "feedback": feedback, "plan": plan}, item)
                    self.assertEqual(state["queue"], [])
                    self.assertEqual(state["completed_trials"], [0, 1, 2])

    def test_same_actor_safe_branch_gets_bounded_replay(self):
        fault = {"fault_id": "f0", "fault_type": "EXCEPTION",
                 "point": {"site": "AliasesManager#process:door:1", "node": "node3",
                           "epoch": 0, "door_ordinal": 1}}
        plan = [fault]
        config = {"case_id": "SOLR-40", "target_branch_replays": 2,
                  "budget": {"max_faults_per_trial": 1}}
        feedback = {"status": "observed", "coverage_ids": [],
                    "closure_coverage_ids": [], "closure_edges": [],
                    "all_faults_effective": True, "target_reached": True,
                    "target_check_reached": True, "target_identity_complete": True,
                    "target_check_actors": ["node3"], "target_threw": False,
                    "target_exception_candidate": False}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = _fresh_state(config)
            state.update({"out": str(root), "completed_trials": [0],
                          "target_binding": {"nodes": ["node3"]}})
            item = {"faults": plan, "signature": sequence_signature(plan),
                    "selection_reason": "dynamic_closure", "priority": 42.0,
                    "queued_at": 0}
            for trial_id in (1, 2, 3):
                (root / "trials" / f"r{trial_id:04d}").mkdir(parents=True)
                _apply_result(state, config,
                              {"trial_id": trial_id, "elapsed_seconds": 1.0,
                               "feedback": feedback, "plan": plan}, item)
                if trial_id < 3:
                    self.assertEqual(len(state["queue"]), 1)
                    item = state["queue"].pop()
                    self.assertEqual(item["selection_reason"], "target_branch_replay")
                    self.assertEqual(item["target_branch_replay_attempt"], trial_id)
            self.assertEqual(state["queue"], [])
            self.assertEqual(state["completed_trials"], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
