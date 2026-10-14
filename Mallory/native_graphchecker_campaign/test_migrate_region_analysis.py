"""Fail-closed migration tests for an analysis-only REGION_STATE upgrade."""

from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign
from Mallory.native_graphchecker_campaign import migrate_region_analysis as migration
from Mallory.native_graphchecker_campaign import test_rebase_local_checkpoint as base_test


class MigrateRegionAnalysisTest(unittest.TestCase):
    def _fixture(self, root: Path):
        fixture = base_test.RebaseLocalCheckpointTest(
            "test_exact_import_changes_only_config_pin_and_is_idempotent")
        args, admitted = fixture._fixture(root)
        (args.local_root / ".campaign.lock").touch()
        runtime, analyzer = root / "runtime.jar", root / "schema2.jar"
        runtime.write_bytes(b"frozen original runtime")
        analyzer.write_bytes(b"source-built schema 2 analyzer")
        weave_file = root / "weave.json"
        campaign._atomic(weave_file, {"java": "/usr/bin/java"})
        old = campaign._load(args.source_config)
        old["runner"]["mode"] = "region_state"
        old["recording"] = {"admission_mode": "region_state_no_schedule",
                            "target_occurrence": "actor#epoch0/exact-target"}
        old["native_weave_config"] = str(weave_file)
        new = copy.deepcopy(old)
        new["runner"].update(local_artifact_root=str(root / "raw"),
                             local_work_root=str(root / "work"))
        new["recording"].update(analysis_engine_jar=str(analyzer),
                                analysis_engine_sha256=migration._sha(analyzer))
        (root / "raw").mkdir()
        (root / "work").mkdir()
        campaign._atomic(args.source_config, old)
        campaign._atomic(args.local_config, new)
        admission = {"schema_version": 1,
                     "origin": {"kind": "native"},
                     "recording_fingerprint": {
                         "admission_mode": "region_state_no_schedule",
                         "engine_jar_sha256": migration._sha(runtime)}}
        campaign._atomic(args.source_root / "recording-admission.json", admission)
        (args.local_root / "recording-admission.json").write_bytes(
            (args.source_root / "recording-admission.json").read_bytes())
        state = campaign._load(args.source_root / "checkpoint.json")
        state["config_sha256"] = migration._sha(args.source_config)
        campaign._atomic(args.source_root / "checkpoint.json", state)
        (args.local_root / "checkpoint.json").write_bytes(
            (args.source_root / "checkpoint.json").read_bytes())
        args.source_checkpoint_sha256 = migration._sha(
            args.source_root / "checkpoint.json")
        args.source_admission_sha256 = migration._sha(
            args.source_root / "recording-admission.json")
        return args, admitted, runtime, analyzer

    @staticmethod
    def _patches(args, admitted, runtime):
        stack = ExitStack()
        stack.enter_context(patch.object(migration, "_require_pg0_read_only"))
        stack.enter_context(patch.object(migration, "_require_local",
                                         side_effect=lambda path, *_: path.resolve()))
        stack.enter_context(patch.object(migration.os, "statvfs",
                                         return_value=argparse.Namespace(f_flag=os.ST_RDONLY)))
        stack.enter_context(patch.object(campaign, "JAR", runtime))
        stack.enter_context(patch.object(campaign, "_validate_config"))
        stack.enter_context(patch.object(campaign, "_validate_local_work_root"))
        stack.enter_context(patch.object(campaign, "_validate_local_artifact_root"))
        stack.enter_context(patch.object(campaign, "_require_exact_resolver_protocol",
                                         return_value={
                                             "analysis_engine_jar_sha256": migration._sha(
                                                 Path(campaign._load(args.local_config)[
                                                     "recording"]["analysis_engine_jar"])),
                                             "capabilities": {
                                                 "schemaVersion": 1,
                                                 "kind": "MALLORY_TARGET_RESOLVER_CAPABILITIES",
                                                 "exactRequestedOccurrenceReceiptSchemaVersion": 2,
                                                 "exactSelectionPolicy":
                                                     "EXACT_REQUESTED_OCCURRENCE_THEN_EARLIEST_EVENT"}}))
        stack.enter_context(patch.object(campaign, "_admit", return_value=admitted))
        return stack

    def test_analysis_only_upgrade_preserves_checkpoint_and_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            args, admitted, runtime, analyzer = self._fixture(Path(directory))
            frozen = (args.source_root / "checkpoint.json").read_bytes()
            with self._patches(args, admitted, runtime):
                receipt = migration.migrate(args)
                self.assertEqual(receipt, migration.migrate(args))
            self.assertEqual(frozen, (args.source_root / "checkpoint.json").read_bytes())
            local = campaign._load(args.local_root / "checkpoint.json")
            source = campaign._load(args.source_root / "checkpoint.json")
            self.assertEqual(source["seen_plan_keys"], local["seen_plan_keys"])
            self.assertEqual(source["active"], local["active"])
            local["config_sha256"] = source["config_sha256"]
            self.assertEqual(source, local)
            self.assertEqual(migration._sha(analyzer), receipt["analysis_engine_sha256"])
            self.assertEqual(2, receipt["resolver_protocol"]["capabilities"][
                "exactRequestedOccurrenceReceiptSchemaVersion"])

    def test_dry_run_writes_no_local_checkpoint_or_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            args, admitted, runtime, _ = self._fixture(Path(directory))
            args.dry_run = True
            before = [(args.local_root / name).read_bytes() for name in (
                "checkpoint.json", "recording-admission.json")]
            with self._patches(args, admitted, runtime):
                receipt = migration.migrate(args)
            self.assertTrue(receipt["dry_run"])
            self.assertEqual(before, [(args.local_root / name).read_bytes()
                                      for name in ("checkpoint.json",
                                                   "recording-admission.json")])
            self.assertFalse((args.local_root /
                              "checkpoint-analysis-migration.json").exists())

    def test_rejects_changed_target_workload_or_runtime(self):
        for change in ("target_site", "main_class", "native_weave_config"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                args, admitted, runtime, _ = self._fixture(Path(directory))
                new = campaign._load(args.local_config)
                if change == "main_class":
                    new["runner"]["main_class"] = "OtherJUnit"
                else:
                    new[change] = "changed"
                campaign._atomic(args.local_config, new)
                with self._patches(args, admitted, runtime):
                    with self.assertRaisesRegex(ValueError, "changes original"):
                        migration.migrate(args)
                self.assertFalse((args.local_root /
                                  "checkpoint-analysis-migration.json").exists())

    def test_rejects_wrong_analyzer_sha_and_non_schema2_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            args, admitted, runtime, _ = self._fixture(Path(directory))
            new = campaign._load(args.local_config)
            new["recording"]["analysis_engine_sha256"] = "0" * 64
            campaign._atomic(args.local_config, new)
            with self._patches(args, admitted, runtime):
                with self.assertRaisesRegex(ValueError, "must differ and match"):
                    migration.migrate(args)
        with tempfile.TemporaryDirectory() as directory:
            args, admitted, runtime, _ = self._fixture(Path(directory))
            with self._patches(args, admitted, runtime), patch.object(
                    campaign, "_require_exact_resolver_protocol",
                    side_effect=ValueError("analysis engine lacks exact occurrence receipt schema 2")):
                with self.assertRaisesRegex(ValueError, "schema 2"):
                    migration.migrate(args)
        with tempfile.TemporaryDirectory() as directory:
            args, admitted, runtime, analyzer = self._fixture(Path(directory))
            bad = {"analysis_engine_jar_sha256": migration._sha(analyzer),
                   "capabilities": {"schemaVersion": 1,
                                    "kind": "MALLORY_TARGET_RESOLVER_CAPABILITIES",
                                    "exactRequestedOccurrenceReceiptSchemaVersion": 1,
                                    "exactSelectionPolicy":
                                        "EXACT_REQUESTED_OCCURRENCE_THEN_EARLIEST_EVENT"}}
            with self._patches(args, admitted, runtime), patch.object(
                    campaign, "_require_exact_resolver_protocol", return_value=bad):
                with self.assertRaisesRegex(ValueError, "schema 2"):
                    migration.migrate(args)

    def test_requires_existing_local_campaign_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            args, admitted, runtime, _ = self._fixture(Path(directory))
            (args.local_root / ".campaign.lock").unlink()
            with self._patches(args, admitted, runtime):
                with self.assertRaisesRegex(ValueError, "campaign lock"):
                    migration.migrate(args)

    def test_rejects_source_trial_changed_during_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            args, admitted, runtime, _ = self._fixture(Path(directory))

            def change_source(*_):
                (args.source_root / "trials/r0001/result.json").write_text("{}")
                return admitted

            with self._patches(args, admitted, runtime), patch.object(
                    campaign, "_admit", side_effect=change_source):
                with self.assertRaises(ValueError):
                    migration.migrate(args)
            self.assertFalse((args.local_root /
                              "checkpoint-analysis-migration.json").exists())

    def test_rejects_changed_accepted_result_or_active_plan(self):
        for kind in ("result", "active"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                args, admitted, runtime, _ = self._fixture(Path(directory))
                if kind == "result":
                    (args.local_root / "trials/r0001").unlink()
                    (args.local_root / "trials/r0001").mkdir()
                    (args.local_root / "trials/r0001/result.json").write_text("{}")
                else:
                    state = campaign._load(args.source_root / "checkpoint.json")
                    state["active"]["key"] = "changed"
                    campaign._atomic(args.source_root / "checkpoint.json", state)
                    (args.local_root / "checkpoint.json").write_bytes(
                        (args.source_root / "checkpoint.json").read_bytes())
                    args.source_checkpoint_sha256 = migration._sha(
                        args.source_root / "checkpoint.json")
                with self._patches(args, admitted, runtime):
                    with self.assertRaises(ValueError):
                        migration.migrate(args)
                self.assertFalse((args.local_root /
                                  "checkpoint-analysis-migration.json").exists())


if __name__ == "__main__":
    unittest.main()
