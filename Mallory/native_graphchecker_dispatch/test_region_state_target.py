import unittest

from Mallory.native_graphchecker_dispatch.region_state_target import (
    bind, healthy_reached_nonfatal, healthy_without_target_throw,
)


class RegionStateTargetTest(unittest.TestCase):
    CHECK = "<C: void follow()>#u52"
    THROW = "<C: void follow()>#u68"

    def setUp(self):
        self.config = {"runner": {"mode": "region_state"},
                       "junit": {"class": "T", "method": "test"},
                       "target_site": self.CHECK + "#1",
                       "target_throw": {"siteId": self.THROW}}
        self.occurrence = {
            "kind": "MALLORY_OBSERVED_TARGET_OCCURRENCE",
            "test": "T#test", "checkSiteId": self.CHECK,
            "fatalOutcome": False, "targetRegionId": "R"}
        self.rows = [{"kind": "STATIC_SCOPE_SITE", "role": "TARGET_SITE",
                      "siteId": self.THROW, "regionId": "R",
                      "guards": [self.CHECK], "guardOutcomes": [False]}]

    def test_binds_concolic_occurrence_to_exact_region_state_site(self):
        bound = bind(self.config, self.occurrence, self.rows)
        self.assertEqual(self.CHECK, bound["target_site"])
        self.assertEqual(self.CHECK + "#1", self.config["target_site"])

    def test_rejects_unrelated_anchor_and_unproven_fatal_arm(self):
        self.config["target_site"] = "<Other: void f()>#u1#1"
        with self.assertRaisesRegex(ValueError, "anchor"):
            bind(self.config, self.occurrence, self.rows)
        self.config["target_site"] = self.CHECK + "#1"
        self.rows[0]["guardOutcomes"] = [True]
        with self.assertRaisesRegex(ValueError, "fatal arm"):
            bind(self.config, self.occurrence, self.rows)

    def test_rejects_wrong_junit_or_target_region(self):
        self.occurrence["test"] = "Other#test"
        with self.assertRaisesRegex(ValueError, "original JUnit"):
            bind(self.config, self.occurrence, self.rows)
        self.occurrence["test"] = "T#test"
        self.rows[0]["regionId"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "target region"):
            bind(self.config, self.occurrence, self.rows)

    def test_healthy_reached_arm_accepts_either_fatal_polarity(self):
        for fatal in (False, True):
            with self.subTest(fatal=fatal):
                receipt = {"fatalOutcome": fatal, "reachedEventCount": 2,
                           "reachedEvents": [
                               {"observedOutcome": not fatal},
                               {"observedOutcome": not fatal}]}
                self.assertTrue(healthy_reached_nonfatal(receipt))
                receipt["reachedEvents"][1]["observedOutcome"] = fatal
                self.assertFalse(healthy_reached_nonfatal(receipt))

    def test_healthy_reached_arm_rejects_missing_or_malformed_evidence(self):
        valid = {"fatalOutcome": True, "reachedEventCount": 1,
                 "reachedEvents": [{"observedOutcome": False}]}
        for change in ({"fatalOutcome": None}, {"fatalOutcome": 1},
                       {"reachedEventCount": 0}, {"reachedEventCount": True},
                       {"reachedEventCount": 2}, {"reachedEvents": []},
                       {"reachedEvents": [{}]},
                       {"reachedEvents": [{"observedOutcome": 0}]}):
            with self.subTest(change=change):
                self.assertFalse(healthy_reached_nonfatal({**valid, **change}))

    def test_healthy_run_rejects_target_throw_even_after_nonfatal_check(self):
        self.assertTrue(healthy_without_target_throw(
            [{"kind": "TARGET_CHECK"}, {"kind": "FAULT_DOOR"}]))
        self.assertFalse(healthy_without_target_throw(
            [{"kind": "TARGET_CHECK"}, {"kind": "TARGET_THROW"}]))


if __name__ == "__main__":
    unittest.main()
