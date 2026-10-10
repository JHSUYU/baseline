#!/usr/bin/env python3
"""Offline promotion tests using the sealed healthy trace."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from healthy_gate import digest, promote, verify_promotion

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
PRIOR = REPO / "data/mallory/healthy_observations/HBASE-28-nonloopback-master-healthy-v1"


class HealthyGateTest(unittest.TestCase):
    def make_campaign(self, root: Path, *, wrong_check: bool = False) -> Path:
        campaign = root / "campaign"
        trial = campaign / "trials/r0000"
        trial.mkdir(parents=True)
        for name in ("result.json", "checkpoint.json"):
            shutil.copyfile(PRIOR / name, campaign / name)
        for name in ("result.json", "events.jsonl.gz"):
            shutil.copyfile(PRIOR / "trials/r0000" / name, trial / name)
        config = json.loads((HERE / "config.json").read_text())
        (campaign / "config.json").write_text(json.dumps(config))
        state = json.loads((campaign / "checkpoint.json").read_text())
        state["config_digest"] = digest(config)
        (campaign / "checkpoint.json").write_text(json.dumps(state))
        result = json.loads((trial / "result.json").read_text())
        for door in result["feedback"]["doors"]:
            if door["event_id"] == "HBASE-28-r0000:2":
                door["local_timeline_evidence"] = {
                    "kind": "observed_local_timeline",
                    "door_event_id": door["event_id"], "door_seq": 2,
                    "target_check_event_id": ("wrong-id" if wrong_check else
                                              "HBASE-28-r0000:3"),
                    "target_check_seq": 3,
                }
        (trial / "result.json").write_text(json.dumps(result))
        (campaign / ".campaign.lock").touch()
        return campaign

    def test_exact_pair_admits_and_promotion_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            campaign = self.make_campaign(Path(directory))
            verdict = promote(campaign)
            self.assertEqual(verdict["queue_entries"], 1)
            self.assertEqual(verdict["door_seq"] + 1, verdict["target_seq"])
            self.assertEqual(verify_promotion(campaign), verdict)

    def test_wrong_check_keeps_faults_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            campaign = self.make_campaign(Path(directory), wrong_check=True)
            with self.assertRaisesRegex(ValueError, "local timeline proof"):
                promote(campaign)
            state = json.loads((campaign / "checkpoint.json").read_text())
            self.assertTrue(state["calibration_only"])
            self.assertEqual(state["completed_trials"], [0])


if __name__ == "__main__":
    unittest.main()
