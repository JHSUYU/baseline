"""The local-root rebase preserves accepted native evidence and active plan."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign
from Mallory.native_graphchecker_campaign import rebase_local_checkpoint as importer


class RebaseLocalCheckpointTest(unittest.TestCase):
    def _fixture(self, root: Path):
        pg0 = root / "pg0"
        old = pg0 / "old"
        local = root / "local"
        old.mkdir(parents=True)
        local.mkdir()
        (local / "frozen-input").symlink_to(old, target_is_directory=True)
        (old / "trials/r0000").mkdir(parents=True)
        (old / "trials/r0001/iteration-native").mkdir(parents=True)
        (local / "trials").mkdir()
        for name in ("r0000", "r0001"):
            (local / "trials" / name).symlink_to(
                local / "frozen-input" / "trials" / name, target_is_directory=True)
        campaign._atomic(old / "recording-admission.json", {"schema_version": 1})
        (local / "recording-admission.json").write_bytes(
            (old / "recording-admission.json").read_bytes())
        healthy = {"case_id": "CASE", "status": "healthy_seed", "faults": []}
        campaign._atomic(old / "trials/r0000/result.json", healthy)
        campaign._atomic(old / "trials/r0000/native-summary.json", {"status": "recorded"})
        fault = {"siteId": "door", "node": "node", "actorEpochOrdinal": 0,
                 "ordinal": 1, "exceptionClass": "java.io.IOException"}
        (old / "trials/r0001/iteration-native/fault-events.jsonl").write_text(
            "fault-applied\n")
        campaign._atomic(old / "trials/r0001/iteration-native/fault-plan.json",
                         {"faults": [fault]})
        result = {"case_id": "CASE", "status": "checked", "faults": [fault],
                  "strict_injection": True, "target_exception_triggered": False,
                  "fault_events_sha256": importer._sha(
                      old / "trials/r0001/iteration-native/fault-events.jsonl")}
        campaign._atomic(old / "trials/r0001/result.json", result)
        next_fault = {**fault, "ordinal": 2}
        weave = root / "woven"
        weave.mkdir()
        campaign._atomic(weave / "native-original-weave-receipt.json", {})
        old_config = {"case_id": "CASE", "runner": {"main_class": "JUnit"},
                      "budget": {"fault_trials": 10}, "target_site": "check"}
        local_config = copy.deepcopy(old_config)
        local_config["runner"].update(local_artifact_root=str(root / "raw"),
                                      local_work_root=str(root / "work"))
        old_config_path, local_config_path = root / "old-config.json", root / "new-config.json"
        campaign._atomic(old_config_path, old_config)
        campaign._atomic(local_config_path, local_config)
        state = {"schema_version": campaign.SCHEMA, "case_id": "CASE",
                 "config_sha256": importer._sha(old_config_path),
                 "budget": old_config["budget"], "terminal": False,
                 "origin": {"kind": "native"}, "zero_vm_sha256": "zero",
                 "runner_classpath_artifacts": [],
                 "weave_receipt_sha256": importer._sha(
                     weave / "native-original-weave-receipt.json"),
                 "healthy": {"result": "trials/r0000/result.json"},
                 "completed_fault_trials": 1,
                 "trials": [{"name": "r0001", "result": "trials/r0001/result.json",
                             "status": "checked", "strict_injection": True,
                             "target_exception_triggered": False}],
                 "seen_plan_keys": [campaign._plan_key([fault]),
                                    campaign._plan_key([next_fault])],
                 "active": {"name": "r0002", "index": 2,
                            "key": campaign._plan_key([next_fault]),
                            "faults": [next_fault]}, "next_trial_index": 3}
        campaign._atomic(old / "checkpoint.json", state)
        (local / "checkpoint.json").write_bytes((old / "checkpoint.json").read_bytes())
        args = argparse.Namespace(pg0=pg0, source_root=old, local_root=local,
                                  frozen_alias=local / "frozen-input",
                                  source_config=old_config_path,
                                  local_config=local_config_path,
                                  source_checkpoint_sha256=importer._sha(
                                      old / "checkpoint.json"),
                                  source_admission_sha256=importer._sha(
                                      old / "recording-admission.json"))
        admitted = {"origin": state["origin"], "zero_vm_sha256": "zero",
                    "runner_classpath_artifacts": [],
                    "weave_config": {"output_classes": str(weave)}}
        return args, admitted

    def test_exact_import_changes_only_config_pin_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args, admitted = self._fixture(Path(directory))
            original = (args.source_root / "checkpoint.json").read_bytes()
            with (patch.object(importer, "_require_pg0_read_only"),
                  patch.object(importer, "_require_local", side_effect=lambda path, *_:
                               path.resolve()),
                  patch.object(importer.os, "statvfs",
                               return_value=argparse.Namespace(f_flag=os.ST_RDONLY)),
                  patch.object(campaign, "_validate_config"),
                  patch.object(campaign, "_validate_local_work_root"),
                  patch.object(campaign, "_validate_local_artifact_root"),
                  patch.object(campaign, "_admit", return_value=admitted)):
                receipt = importer.rebase(args)
                self.assertEqual(1, receipt["completed_fault_trials"])
                self.assertEqual(2, receipt["active_index"])
                self.assertEqual(receipt, importer.rebase(args))
            self.assertEqual(original, (args.source_root / "checkpoint.json").read_bytes())
            rebased = campaign._load(args.local_root / "checkpoint.json")
            frozen = campaign._load(args.source_root / "checkpoint.json")
            self.assertEqual(importer._sha(args.local_config), rebased["config_sha256"])
            rebased["config_sha256"] = frozen["config_sha256"]
            self.assertEqual(frozen, rebased)

    def test_rejects_changed_target_before_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args, admitted = self._fixture(Path(directory))
            changed = campaign._load(args.local_config)
            changed["target_site"] = "different"
            campaign._atomic(args.local_config, changed)
            with (patch.object(importer, "_require_pg0_read_only"),
                  patch.object(importer, "_require_local", side_effect=lambda path, *_:
                               path.resolve()),
                  patch.object(importer.os, "statvfs",
                               return_value=argparse.Namespace(f_flag=os.ST_RDONLY)),
                  patch.object(campaign, "_validate_config")):
                with self.assertRaisesRegex(ValueError, "more than local runner roots"):
                    importer.rebase(args)
            self.assertFalse((args.local_root / "checkpoint-rebase.json").exists())


if __name__ == "__main__":
    unittest.main()
