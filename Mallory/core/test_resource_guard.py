"""Capacity gates fail before a trial when a local or shared limit is hit."""

import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.core.resource_guard import (CapacityGuardStop, check_capacity,
                                        load_capacity_guard, wait_with_capacity)


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
                       side_effect=[95, 2000, 2000]), patch(
                       "Mallory.core.resource_guard._memory_available",
                       return_value=2000), patch(
                       "Mallory.core.resource_guard._allocated_tree",
                       side_effect=[0, 0]):
                self.assertIsNone(check_capacity(guard, private,
                                                 "running")["reason"])
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

    def test_running_guard_stops_jvm_process_group(self):
        with tempfile.TemporaryDirectory() as temp:
            process = subprocess.Popen(["/bin/sleep", "3"], start_new_session=True)
            try:
                guard = {"poll_seconds": 0.01}
                stopped = {"phase": "running", "reason": "pg0_stop_floor",
                           "sample": {"pg0_available_bytes": 8}}
                with patch("Mallory.core.resource_guard.check_capacity",
                           return_value=stopped):
                    with self.assertRaises(CapacityGuardStop) as caught:
                        wait_with_capacity(process, 2, guard, Path(temp))
                self.assertEqual(stopped, caught.exception.receipt)
                self.assertIsNotNone(process.poll())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()


if __name__ == "__main__":
    unittest.main()
