"""Capacity gates fail before a trial when a local or shared limit is hit."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.core.resource_guard import check_capacity, load_capacity_guard


class ResourceGuardTest(unittest.TestCase):
    def test_pg0_private_and_durable_limits_have_distinct_stop_reasons(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pg0 = root / "pg0"
            scratch = root / "scratch"
            private = root / "private"
            for path in (pg0, scratch, private):
                path.mkdir()
            config = {"pg0_path": str(pg0), "root_path": str(root),
                      "scratch_path": str(scratch),
                      "durable_path": str(pg0 / "campaign"),
                      "pg0_start_min_bytes": 100,
                      "pg0_stop_max_bytes": 90,
                      "root_min_bytes": 1, "scratch_min_bytes": 1,
                      "memory_min_bytes": 1,
                      "private_max_bytes": 1000,
                      "durable_max_bytes": 100,
                      "poll_seconds": 3}
            guard = load_capacity_guard(config, private)
            with patch("Mallory.core.resource_guard._available",
                       side_effect=[99, 2000, 2000]), patch(
                       "Mallory.core.resource_guard._memory_available",
                       return_value=2000), patch(
                       "Mallory.core.resource_guard._allocated_tree",
                       side_effect=[0, 0]):
                self.assertEqual("pg0_start_floor", check_capacity(
                    guard, private, "fault")["reason"])
            with patch("Mallory.core.resource_guard._available",
                       side_effect=[90, 2000, 2000]), patch(
                       "Mallory.core.resource_guard._memory_available",
                       return_value=2000), patch(
                       "Mallory.core.resource_guard._allocated_tree",
                       side_effect=[0, 0]):
                self.assertEqual("pg0_stop_floor", check_capacity(
                    guard, private, "fault")["reason"])
            with patch("Mallory.core.resource_guard._available",
                       side_effect=[200, 2000, 2000]), patch(
                       "Mallory.core.resource_guard._memory_available",
                       return_value=2000), patch(
                       "Mallory.core.resource_guard._allocated_tree",
                       side_effect=[1000, 0]):
                self.assertEqual("private_cap", check_capacity(
                    guard, private, "fault")["reason"])
            with patch("Mallory.core.resource_guard._available",
                       side_effect=[200, 2000, 2000]), patch(
                       "Mallory.core.resource_guard._memory_available",
                       return_value=2000), patch(
                       "Mallory.core.resource_guard._allocated_tree",
                       side_effect=[0, 100]):
                self.assertEqual("durable_cap", check_capacity(
                    guard, private, "fault")["reason"])


if __name__ == "__main__":
    unittest.main()
