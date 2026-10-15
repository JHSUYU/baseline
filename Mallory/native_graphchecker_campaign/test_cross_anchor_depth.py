"""The optional global depth quota cannot phase-lock to anchor rotation."""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from Mallory.native_graphchecker_campaign import campaign


def item(name: str, anchor: str, depth: int, *, strict: bool = True,
         phase: str = "before_selected_target") -> dict:
    return {"key": name, "anchor_address": anchor,
            "faults": [{"siteId": f"<Test: void io()>#u{n}", "node": "n0",
                        "actorEpochOrdinal": 0, "occurrenceId": f"{name}-{n}",
                        "ordinal": n, "exceptionClass": "java.io.IOException"}
                       for n in range(depth)],
            "depth_feedback": {"strict_post_fault_target": strict,
                               "score": depth},
            "target_phase": phase, "peer_relation": "same_peer_before_target",
            "same_site_descendant": True, "novelty": 0}


def state(completed: int, queue: list[dict], trials: list[dict] | None = None
          ) -> dict:
    return {"scheduler_version": 15, "completed_fault_trials": completed,
            "budget": {"max_faults_per_trial": 12}, "queue": queue,
            "trials": trials or [], "fault_id_attempts": {},
            "multi_anchor_addresses": ["anchor-A", "anchor-B"]}


class CrossAnchorDepthTest(unittest.TestCase):
    def test_opt_in_version_is_recorded_in_fresh_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "native-original-weave-receipt.json").write_text("{}")
            config = {"case_id": "generic", "budget": {"fault_trials": 16,
                      "max_faults_per_trial": 12, "seconds": 3600},
                      "recording": {"multi_target_max_anchors": 8,
                      "repeated_rpc_occurrence_policy":
                      "repeated_rpc_pretarget_v1",
                      "cross_anchor_strict_depth_policy": "global_quarter_v1"}}
            admitted = {"weave_config": {"output_classes": str(root)},
                        "origin": {}, "zero_vm_sha256": "a",
                        "runner_classpath_artifacts": []}
            fresh = campaign._new_state(config, "config-sha", admitted)
            self.assertEqual(15, fresh["scheduler_version"])
            self.assertEqual("global_quarter_v1", fresh[
                "multi_anchor_config"]["cross_anchor_strict_depth_policy"])

    def test_fair_slot_selects_descendant_from_nonrotating_anchor(self) -> None:
        # Completed=2 would rotate to anchor A under ordinary round robin.
        # Only anchor B has a strict depth-two descendant.
        one = item("one", "anchor-A", 1)
        deep = item("deep", "anchor-B", 2)
        queue = [one, deep]
        selected = campaign._pick(state(2, queue))
        self.assertIs(selected, deep)
        self.assertEqual([one], queue)

    def test_fair_slot_uses_fewer_accepted_deep_trials(self) -> None:
        a = item("a", "anchor-A", 3)
        b = item("b", "anchor-B", 2)
        trials = [{"anchor_address": "anchor-A", "faults": [1, 2],
                   "strict_injection": True}]
        self.assertIs(b, campaign._pick(state(2, [a, b], trials)))

    def test_progress_slot_deepens_verified_prefix(self) -> None:
        short = item("short", "anchor-A", 2)
        deep = item("deep", "anchor-B", 4)
        self.assertIs(deep, campaign._pick(state(6, [short, deep])))

    def test_unverified_or_posttarget_descendants_are_ineligible(self) -> None:
        invalid = item("invalid", "anchor-B", 4, strict=False)
        late = item("late", "anchor-B", 3,
                    phase="after_selected_target")
        valid = item("valid", "anchor-A", 2)
        self.assertIs(valid, campaign._pick(state(2, [invalid, late, valid])))

    def test_configured_maximum_is_respected(self) -> None:
        excessive = item("excessive", "anchor-B", 13)
        valid = item("valid", "anchor-A", 2)
        self.assertIs(valid, campaign._pick(state(2, [excessive, valid])))


if __name__ == "__main__":
    unittest.main()
