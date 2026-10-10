import unittest

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
            self.assertIsNone(run_campaign.scheduler._replay_point(
                {"point": {**base, "node": "shard-2"}}))
            self.assertIsNone(run_campaign.scheduler._replay_point(
                {"point": {**base, "site": "unqualified"}}))
        finally:
            run_campaign.scheduler._replay_point = original_replay
            run_campaign.campaign.mutate = original_mutate
            run_campaign.campaign._apply_result = original_apply


if __name__ == "__main__":
    unittest.main()
