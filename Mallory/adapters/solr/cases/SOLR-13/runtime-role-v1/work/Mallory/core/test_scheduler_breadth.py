"""Bounded single-fault breadth without starving deeper sequences."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from .campaign import validate_config
from .scheduler import pick_next


def _candidate(name: str, *, depth: int, priority: float,
               reason: str = "dynamic_closure") -> dict:
    return {"priority": priority, "queued_at": 0, "signature": name,
            "selection_reason": reason,
            "faults": [{"fault_id": f"{name}-{index}"} for index in range(depth)]}


class SchedulerBreadthTest(unittest.TestCase):
    def test_two_single_fault_picks_then_one_unrestricted_pick(self):
        queue = [_candidate("deep", depth=2, priority=100),
                 _candidate("single-a", depth=1, priority=20),
                 _candidate("single-b", depth=1, priority=10)]
        config = {"single_fault_breadth_interval": 3}
        self.assertEqual("single-a", pick_next(queue, 1, 0, config)["signature"])
        resumed_queue = copy.deepcopy(queue)
        self.assertEqual("single-b", pick_next(queue, 2, 1, config)["signature"])
        self.assertEqual("single-b", pick_next(resumed_queue, 2, 1, config)["signature"])
        self.assertEqual("deep", pick_next(queue, 3, 2, config)["signature"])

    def test_replay_retains_priority_and_default_selection_is_unchanged(self):
        deep = _candidate("deep", depth=3, priority=20)
        single = _candidate("single", depth=1, priority=10)
        replay = _candidate("replay", depth=2, priority=100,
                            reason="candidate_replay")
        self.assertEqual("deep", pick_next([deep.copy(), single.copy()], 1, 0,
                                             {})["signature"])
        self.assertEqual("replay", pick_next([deep.copy(), single.copy(), replay],
                                               1, 0,
                                               {"single_fault_breadth_interval": 3})["signature"])
        self.assertEqual("deep", pick_next([deep.copy()], 1, 0,
                                             {"single_fault_breadth_interval": 3})["signature"])

    def test_config_rejects_nonpositive_or_boolean_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"case_id": "C", "system": "solr", "cluster_test": "T#test",
                      "command": ["true"], "cwd": str(Path(directory)),
                      "target": {"check_sites": ["C#check"], "throw_site": "C#throw",
                                 "exception_class": "java.io.IOException"},
                      "budget": {"trials": 4, "seconds": 100, "max_faults_per_trial": 6,
                                 "trial_timeout_seconds": 20}}
            for invalid in (True, 0, 1, -2, 2.5, "3"):
                with self.subTest(value=invalid), self.assertRaisesRegex(
                        ValueError, "single_fault_breadth_interval"):
                    validate_config({**config, "single_fault_breadth_interval": invalid})
            validate_config({**config, "single_fault_breadth_interval": 3})


if __name__ == "__main__":
    unittest.main()
