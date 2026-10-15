"""No-JVM identity checks for the independent repeated-RPC campaign."""

from __future__ import annotations

import copy
import unittest

from Mallory.adapters.hdfs.graphchecker_port.balancer_short_lifetime_repeat_v1 import stage_config


class StageConfigTest(unittest.TestCase):
    def source(self) -> dict:
        return {"case_id": "HDFS-11-TIMING-LIFETIME-PEER-V2",
                "junit": {"class":
                          "org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer",
                          "method": "testEncryptedBalancer0"},
                "budget": {"fault_trials": 64, "max_faults_per_trial": 6,
                           "seconds": 7200},
                "recording": {"multi_target_max_anchors": 4,
                              "control_plane_peer_policy":
                              "same_peer_pretarget_late_repeated_quarter",
                              "static_may_scope_map_sha256": "pinned"},
                "runner": {"classpath": ["unchanged"],
                           "local_artifact_root": "/old/raw",
                           "local_work_root": "/old/work"},
                "target_throw": {"site": "unchanged"},
                "target_site": {"site": "unchanged"}}

    def test_only_budget_identity_policy_and_private_roots_change(self) -> None:
        source = self.source()
        original = copy.deepcopy(source)
        derived = stage_config.derive(source)
        self.assertEqual(source, original)
        self.assertEqual(128, derived["budget"]["fault_trials"])
        self.assertEqual(12, derived["budget"]["max_faults_per_trial"])
        self.assertEqual(14400, derived["budget"]["seconds"])
        self.assertEqual("repeated_rpc_pretarget_v1", derived["recording"][
            "repeated_rpc_occurrence_policy"])
        self.assertEqual(source["target_throw"], derived["target_throw"])
        self.assertEqual(source["target_site"], derived["target_site"])
        self.assertEqual(source["runner"]["classpath"],
                         derived["runner"]["classpath"])
        stripped = copy.deepcopy(derived)
        stripped["case_id"] = source["case_id"]
        stripped["budget"] = source["budget"]
        stripped["recording"].pop("repeated_rpc_occurrence_policy")
        stripped["runner"]["local_artifact_root"] = "/old/raw"
        stripped["runner"]["local_work_root"] = "/old/work"
        self.assertEqual(source, stripped)

    def test_rejects_different_junit_or_policy(self) -> None:
        source = self.source()
        source["junit"]["method"] = "different"
        with self.assertRaises(ValueError):
            stage_config.derive(source)
        source = self.source()
        source["recording"]["control_plane_peer_policy"] = "different"
        with self.assertRaises(ValueError):
            stage_config.derive(source)


if __name__ == "__main__":
    unittest.main()
