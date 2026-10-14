"""Partial chain reporting never grants a native checklist completion."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch.checklist import (
    DEFAULT_INVENTORY, DEFAULT_OWNERSHIP,
)

from .chain_progress import publish_progress, validate_progress
from .results import export_native_results
from .test_chain_completion import ChainedCompletionTest, THROW


class ChainProgressTest(unittest.TestCase):
    def fixture(self) -> tuple[ChainedCompletionTest, dict]:
        source = ChainedCompletionTest(
            methodName="test_complete_requires_budget_and_full_graph_audit")
        source.setUp()
        self.addCleanup(source.doCleanups)
        item = {"case_id": source.case,
                "workload": {"selected_selector": "SampleTest#testCluster"},
                "target": {"site_id": THROW["siteId"],
                           "target_exception": THROW["exceptionClass"]}}
        return source, item

    def test_partial_progress_pins_formal_receipt_without_completion(self) -> None:
        source, item = self.fixture()
        manifest = source.manifest([source.segment("one")], fault_budget=2)
        state = source.root / "queue-state"
        progress = publish_progress(item=item, manifest=manifest, state_root=state)
        self.assertEqual(progress["completed_fault_trials"], 1)
        self.assertEqual(progress["distinct_fault_plan_keys"], 1)
        self.assertEqual(progress["status"], "partial")
        self.assertFalse((state / ".native-queue/completions" /
                          f"{source.case}.json").exists())
        pin = Path(progress["pin_path"])
        self.assertEqual(validate_progress(item, pin), progress)
        result = source.root / "one/trials/r0001/result.json"
        result.write_text(result.read_text() + " ")
        with self.assertRaises(ValueError):
            validate_progress(item, pin)

    def test_no_authority_or_full_chain_is_not_partial_progress(self) -> None:
        source, item = self.fixture()
        segment = source.segment("one")
        state = source.root / "queue-state"
        full = source.manifest([segment])
        with self.assertRaisesRegex(ValueError, "formal partial authority"):
            publish_progress(item=item, manifest=full, state_root=state)
        partial = source.manifest([segment], fault_budget=2)
        value = json.loads(partial.read_text())
        del value["formal_budget_authority"]
        partial.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "formal partial authority"):
            publish_progress(item=item, manifest=partial, state_root=state)
        self.assertFalse((state / ".native-queue/chain-progress" /
                          f"{source.case}.json").exists())

    def test_wrong_target_is_rejected_before_pointer_published(self) -> None:
        source, item = self.fixture()
        item["target"]["site_id"] = "<Other: void target()>#u9"
        manifest = source.manifest([source.segment("one")], fault_budget=2)
        state = source.root / "queue-state"
        with self.assertRaisesRegex(ValueError, "target differs from inventory"):
            publish_progress(item=item, manifest=manifest, state_root=state)
        self.assertFalse((state / ".native-queue/chain-progress" /
                          f"{source.case}.json").exists())

    def test_alternate_original_junit_needs_source_attestation(self) -> None:
        source, item = self.fixture()
        segment = source.segment("one")
        config_path = Path(segment["config"]["path"])
        config = json.loads(config_path.read_text())
        config["junit"]["method"] = "testOtherOriginalCluster"
        config_path.write_text(json.dumps(config) + "\n")
        from .chain_completion import sha256
        segment["config"]["sha256"] = sha256(config_path)
        checkpoint_path = Path(segment["checkpoint"]["path"])
        checkpoint = json.loads(checkpoint_path.read_text())
        checkpoint["config_sha256"] = sha256(config_path)
        checkpoint_path.write_text(json.dumps(checkpoint) + "\n")
        segment["checkpoint"]["sha256"] = sha256(checkpoint_path)
        summary_path = Path(segment["summary"]["path"])
        summary_path.write_text(json.dumps(checkpoint) + "\n")
        segment["summary"]["sha256"] = sha256(summary_path)
        del segment["frozen_audit"]
        manifest = source.manifest([segment], fault_budget=2)
        state = source.root / "queue-state"
        with self.assertRaisesRegex(ValueError,
                                    "alternate original JUnit attestation"):
            publish_progress(item=item, manifest=manifest, state_root=state)
        self.assertFalse((state / ".native-queue/chain-progress" /
                          f"{source.case}.json").exists())

    def test_progress_advances_only_with_new_distinct_plans(self) -> None:
        source, item = self.fixture()
        first = source.segment("first")
        initial = source.manifest([first], fault_budget=3)
        initial_pin = source.root / "chain-v1.json"
        initial_pin.write_bytes(initial.read_bytes())
        state = source.root / "queue-state"
        first_progress = publish_progress(item=item, manifest=initial_pin,
                                          state_root=state)
        second = source.segment("second", previous=first, fault_ordinal=2)
        advanced = source.manifest([first, second], fault_budget=3)
        advanced_pin = source.root / "chain-v2.json"
        advanced_pin.write_bytes(advanced.read_bytes())
        second_progress = publish_progress(item=item, manifest=advanced_pin,
                                           state_root=state)
        self.assertEqual(second_progress["completed_fault_trials"], 2)
        self.assertNotEqual(first_progress["receipt_sha256"],
                            second_progress["receipt_sha256"])
        self.assertTrue(Path(first_progress["receipt_path"]).is_file())
        with self.assertRaisesRegex(ValueError, "cannot regress"):
            publish_progress(item=item, manifest=initial_pin,
                             state_root=state)

    def test_export_keeps_partial_counts_separate_from_terminal_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config, state, results = (root / name for name in
                                      ("config", "state", "results"))
            config.mkdir()
            pin = state / ".native-queue/chain-progress/ZOOKEEPER-10.json"
            pin.parent.mkdir(parents=True)
            pin.write_text("{}\n")
            progress = {"status": "partial", "completed_fault_trials": 32,
                        "strict_fault_trials": 32,
                        "strict_target_retained_fault_trials": 28,
                        "strict_in_target_closure_trials": 23,
                        "exact_target_throw_trials": 0,
                        "elapsed_seconds": 1717.727,
                        "manifest_path": str(root / "manifest.json"),
                        "receipt_path": str(root / "receipt.json"),
                        "pin_path": str(pin)}
            with patch("Mallory.native_graphchecker_queue.results.validate_progress",
                       return_value=progress):
                output, tsv = export_native_results(
                    DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, config, state, results)
            document = json.loads(output.read_text())
            row = next(row for row in document["rows"] if row["case_id"] ==
                       "ZOOKEEPER-10")
            self.assertEqual(document["verified_terminal_count"], 0)
            self.assertEqual(row["native_state"], "partial_chain_audited")
            self.assertEqual(row["chain_progress"], progress)
            self.assertFalse(row["native_tested_complete"])
            self.assertIsNone(row["fault_trials"])
            self.assertIsNone(row["elapsed_seconds"])
            self.assertIn("chain_progress", tsv.read_text().splitlines()[0])


if __name__ == "__main__":
    unittest.main()
