#!/usr/bin/env python3
"""Offline gate regressions from the sealed v6 healthy trace; no JVM launched."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from healthy_gate import digest, promote, verify_pair, verify_promotion

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
ARCHIVE = ROOT / "data/mallory/healthy_observations/HBASE-34-construction-healthy-v6"


class HealthyGateTest(unittest.TestCase):
    def make_campaign(self, root: Path) -> Path:
        campaign = root / "campaign"
        trial = campaign / "trials/r0000"
        trial.mkdir(parents=True)
        for name in ("result.json", "checkpoint.json"):
            shutil.copy2(ARCHIVE / name, campaign / name)
        for name in ("result.json", "events.jsonl.gz"):
            shutil.copy2(ARCHIVE / "trials/r0000" / name, trial / name)
        config = json.loads((HERE / "config.json").read_text())
        (campaign / "config.json").write_text(json.dumps(config))
        state = json.loads((campaign / "checkpoint.json").read_text())
        state["config_digest"] = digest(config)
        state["queue"] = [row for row in state["queue"] if
                          row["faults"][0]["point"]["node"] == "rs0"]
        (campaign / "checkpoint.json").write_text(json.dumps(state))
        (campaign / ".campaign.lock").touch()
        return campaign

    def test_sealed_trace_has_candidate_state_witness(self) -> None:
        verdict = verify_pair(ARCHIVE)
        self.assertEqual(verdict["target_actor"], "rs0")
        self.assertEqual(verdict["state_edge_certainty"], "candidate")
        self.assertEqual(len(verdict["allowed_points"]), 2)

    def test_promote_only_named_closure_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = self.make_campaign(Path(tmp))
            verdict = promote(campaign)
            self.assertEqual(verdict["queue_entries"], 2)
            self.assertFalse(json.loads((campaign / "checkpoint.json").read_text())["calibration_only"])
            self.assertEqual(verify_promotion(campaign)["target_actor"], "rs0")

    def test_reject_missing_candidate_state_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = self.make_campaign(Path(tmp))
            trial_path = campaign / "trials/r0000/result.json"
            trial = json.loads(trial_path.read_text())
            trial["feedback"]["closure_edges"] = []
            trial_path.write_text(json.dumps(trial))
            with self.assertRaisesRegex(ValueError, "candidate state edge absent"):
                promote(campaign)

    def test_reject_outside_closure_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = self.make_campaign(Path(tmp))
            state_path = campaign / "checkpoint.json"
            state = json.loads(state_path.read_text())
            row = json.loads(json.dumps(state["queue"][0]))
            row["faults"][0]["point"]["node"] = "master0"
            state["queue"].append(row)
            state_path.write_text(json.dumps(state))
            with self.assertRaisesRegex(ValueError, "unverified fault point"):
                promote(campaign)


if __name__ == "__main__":
    unittest.main()
