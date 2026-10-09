"""A dead coordinator must not make an unfinished lane look complete."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Mallory.dispatch.watch_collect_lanes import pending_terminal_cases


class WatchCollectLanesTest(unittest.TestCase):
    def test_missing_or_unfinished_queue_keeps_watch_alive(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.assertEqual(["ready_manifest_missing_or_invalid"],
                             pending_terminal_cases(repo, "node1-lane5"))
            ready = repo / "data/mallory/dispatch/node1-lane5/handoff/pins/ready.json"
            ready.parent.mkdir(parents=True)
            ready.write_text(json.dumps({"cases": [
                {"case_id": "HBASE-29", "state": "ready"},
                {"case_id": "HBASE-30", "state": "ready"}]}), encoding="utf-8")
            with patch("Mallory.dispatch.watch_collect_lanes.finalized",
                       side_effect=lambda _root, case_id: case_id == "HBASE-29"):
                self.assertEqual(["HBASE-30"], pending_terminal_cases(repo, "node1-lane5"))
            with patch("Mallory.dispatch.watch_collect_lanes.finalized", return_value=True):
                self.assertEqual([], pending_terminal_cases(repo, "node1-lane5"))


if __name__ == "__main__":
    unittest.main()
