"""Exact infrastructure replay and checkpoint-bounded campaign controls."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign as core


class ReplayControlsTest(unittest.TestCase):
    @staticmethod
    def _item(key: str) -> dict:
        return {"key": key, "tier": "observed_closure", "novelty": 0,
                "enqueued_at": 0, "attempt": 0,
                "faults": [{"siteId": key, "exceptionClass": "java.io.IOException"}]}

    def test_exact_replay_precedes_scheduler_and_consumes_one_key(self) -> None:
        for version in (1, core.SCHEDULER_VERSION):
            with self.subTest(version=version):
                state = {"queue": [self._item("first"), self._item("replay")],
                         "completed_fault_trials": 2,
                         "scheduler_version": version,
                         "required_replay_plan_keys": ["replay"]}
                self.assertEqual("replay", core._pick(state)["key"])
                self.assertEqual([], state["required_replay_plan_keys"])
                self.assertEqual(["first"], [item["key"] for item in state["queue"]])

    def test_missing_or_ambiguous_replay_fails_without_queue_mutation(self) -> None:
        for queue in ([self._item("other")],
                      [self._item("replay"), self._item("replay")]):
            with self.subTest(queue=queue):
                state = {"queue": queue.copy(),
                         "scheduler_version": core.SCHEDULER_VERSION,
                         "required_replay_plan_keys": ["replay"]}
                with self.assertRaisesRegex(ValueError, "missing from queue"):
                    core._pick(state)
                self.assertEqual(queue, state["queue"])
                self.assertEqual(["replay"], state["required_replay_plan_keys"])

    def test_invalid_replay_manifest_fails_closed(self) -> None:
        state = {"queue": [self._item("replay")],
                 "scheduler_version": core.SCHEDULER_VERSION,
                 "required_replay_plan_keys": ["replay", "replay"]}
        with self.assertRaisesRegex(ValueError, "invalid required replay"):
            core._pick(state)
        self.assertEqual(1, len(state["queue"]))

    def test_round_stop_uses_accepted_checkpoint_without_running_trial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config = {"case_id": "CASE", "budget": {
                "fault_trials": 8, "seconds": 7200,
                "max_faults_per_trial": 4}}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            campaign_root = root / "campaign"
            campaign_root.mkdir()
            weave = root / "woven"
            weave.mkdir()
            (weave / "native-original-weave-receipt.json").write_text(
                "{}", encoding="utf-8")
            admitted = {"weave_config": {"output_classes": str(weave)},
                        "origin": {"kind": "original_junit"},
                        "zero_vm_sha256": "zero-pin",
                        "runner_classpath_artifacts": []}
            state = {"schema_version": core.SCHEMA,
                     "case_id": "CASE", "config_sha256": core._sha(config_path),
                     "budget": config["budget"],
                     "weave_receipt_sha256": core._sha(
                         weave / "native-original-weave-receipt.json"),
                     "origin": admitted["origin"],
                     "zero_vm_sha256": "zero-pin",
                     "runner_classpath_artifacts": [],
                     "healthy": {"status": "healthy_seed"},
                     "completed_fault_trials": 2,
                     "elapsed_seconds": 0.0,
                     "stop_after_completed_fault_trials": 2,
                     "queue": [self._item("next")], "active": None,
                     "terminal": False, "status": "running"}
            core._atomic(campaign_root / "checkpoint.json", state)
            with (patch.object(core, "_validate_config"),
                  patch.object(core, "_validate_local_work_root"),
                  patch.object(core, "_validate_local_artifact_root"),
                  patch.object(core, "_admit", return_value=admitted),
                  patch.object(core, "_resume_active") as resume,
                  patch.object(core, "_pick") as pick,
                  patch.object(core, "_verify_terminal_peer_ranking_receipts")):
                result = core.run_campaign(config_path, campaign_root)
                self.assertEqual("bounded_checkpoint_stop", result["status"])
                self.assertFalse(result["terminal"])
                self.assertEqual(2, result["completed_fault_trials"])
                self.assertEqual("bounded_checkpoint_stop", core._load(
                    campaign_root / "checkpoint.json")["status"])
                resume.assert_called_once()
                pick.assert_not_called()

                # Raising the operator's round bound resumes from the same
                # accepted checkpoint and reaches a new scheduler selection.
                saved = core._load(campaign_root / "checkpoint.json")
                saved["stop_after_completed_fault_trials"] = 3
                core._atomic(campaign_root / "checkpoint.json", saved)
                pick.side_effect = RuntimeError("next plan selected")
                with self.assertRaisesRegex(RuntimeError, "next plan selected"):
                    core.run_campaign(config_path, campaign_root)
                pick.assert_called_once()
                pick.reset_mock(side_effect=True)

                # The formal trial and time budgets take precedence over a
                # matching local stop bound; neither becomes a partial pause.
                for completed, elapsed, expected in (
                        (8, 0.0, "complete_trial_budget"),
                        (2, 7200.0, "complete_time_budget")):
                    with self.subTest(expected=expected):
                        saved = core._load(campaign_root / "checkpoint.json")
                        saved.update(status="running", terminal=False,
                                     completed_fault_trials=completed,
                                     elapsed_seconds=elapsed,
                                     stop_after_completed_fault_trials=completed)
                        core._atomic(campaign_root / "checkpoint.json", saved)
                        finished = core.run_campaign(config_path, campaign_root)
                        self.assertTrue(finished["terminal"])
                        self.assertEqual(expected, finished["status"])
                        pick.assert_not_called()


if __name__ == "__main__":
    unittest.main()
