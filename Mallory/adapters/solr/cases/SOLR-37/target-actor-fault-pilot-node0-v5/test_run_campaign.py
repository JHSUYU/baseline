import unittest
import tempfile
from pathlib import Path

import run_campaign


class StrictRuntimeTest(unittest.TestCase):
    def test_replay_adds_required_qualifiers_and_rejects_other_actors(self):
        original_replay = run_campaign.scheduler._replay_point
        original_mutate = run_campaign.campaign.mutate
        original_apply = run_campaign.campaign._apply_result
        try:
            run_campaign.install_strict_runtime()
            base = {"site": run_campaign.DOOR, "node": "shard-4",
                    "epoch": 0, "door_ordinal": 7}
            point = run_campaign.scheduler._replay_point({"point": base})
            self.assertEqual(run_campaign.RESOURCE, point["resource"])
            self.assertEqual(run_campaign.REGION, point["region"])
            self.assertEqual("watcher_region", point["occurrence_kind"])
            self.assertNotIn("occurrence", point)
            self.assertEqual("shard-2", run_campaign.scheduler._replay_point(
                {"point": {**base, "node": "shard-2"}})["node"])
            self.assertIsNone(run_campaign.scheduler._replay_point(
                {"point": {**base, "node": "control"}}))
            self.assertIsNone(run_campaign.scheduler._replay_point(
                {"point": {**base, "site": "unqualified"}}))
        finally:
            run_campaign.scheduler._replay_point = original_replay
            run_campaign.campaign.mutate = original_mutate
            run_campaign.campaign._apply_result = original_apply

    def test_mutation_selects_witnessed_door_on_actual_target_actor(self):
        original_replay = run_campaign.scheduler._replay_point
        original_mutate = run_campaign.campaign.mutate
        original_apply = run_campaign.campaign._apply_result
        selected = []
        try:
            run_campaign.campaign.mutate = lambda parent, feedback, config: selected.extend(
                feedback["doors"]) or []
            run_campaign.install_strict_runtime()
            def door(node, ordinal):
                return {"site": run_campaign.DOOR,
                        "point": {"site": run_campaign.DOOR, "node": node,
                                  "epoch": 0, "door_ordinal": ordinal}}
            feedback = {"doors": [door("shard-4", 1), door("shard-2", 1),
                                  door("shard-2", 2)],
                        "target_instances": [{"node": "shard-2", "epoch": 0}],
                        "strict_qualified_points": [{"node": "shard-2", "epoch": 0,
                                                     "door_ordinal": 2}]}
            run_campaign.campaign.mutate([], feedback, {})
            self.assertEqual([door("shard-2", 2)], selected)
        finally:
            run_campaign.scheduler._replay_point = original_replay
            run_campaign.campaign.mutate = original_mutate
            run_campaign.campaign._apply_result = original_apply

    def test_missing_trace_fails_closed_without_losing_trial_result(self):
        original_replay = run_campaign.scheduler._replay_point
        original_mutate = run_campaign.campaign.mutate
        original_apply = run_campaign.campaign._apply_result
        captured = []
        try:
            run_campaign.campaign._apply_result = lambda state, config, result, item: captured.append(result)
            run_campaign.install_strict_runtime()
            with tempfile.TemporaryDirectory() as directory:
                result = {"trial_id": 1, "plan": [{"fault_id": "f1"}],
                          "feedback": {"status": "observed", "target_reached": True,
                                       "all_faults_effective": True,
                                       "target_exception_candidate": True}}
                run_campaign.campaign._apply_result(
                    {"out": directory}, {}, result, None)
                audit = Path(directory) / "trials/r0001/strict-audit.json"
                self.assertTrue(audit.is_file())
                self.assertEqual("missing_compressed_trace", result["strict_audit"]["reason"])
                self.assertFalse(result["feedback"]["target_reached"])
                self.assertFalse(result["feedback"]["all_faults_effective"])
                self.assertFalse(result["feedback"]["target_exception_candidate"])
                self.assertEqual(1, len(captured))
        finally:
            run_campaign.scheduler._replay_point = original_replay
            run_campaign.campaign.mutate = original_mutate
            run_campaign.campaign._apply_result = original_apply


if __name__ == "__main__":
    unittest.main()
