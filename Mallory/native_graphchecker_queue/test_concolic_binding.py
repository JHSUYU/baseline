"""Direct original concolic admission can be adopted without replaying JUnit."""

from __future__ import annotations

import copy
import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch.checklist import (
    DEFAULT_INVENTORY, _native_case_files, inspect_case, load_inventory,
)
from .bind_and_run import binding_for


def put(path: Path, value: dict | str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DirectConcolicBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        cases, _ = load_inventory(DEFAULT_INVENTORY)
        self.item = copy.deepcopy(next(case for case in cases if case[
            "case_id"] == "ZOOKEEPER-03"))
        source = self.root / "Target.java"
        self.item["target"]["source_path"] = "Target.java"
        self.item["target"]["source_sha256"] = put(source, "throw target;\n")
        source_archive = self.root / "shared" / "Target.java"
        put(source_archive, "throw target;\n")
        self.config_root = self.root / "config"
        self.state_root = self.root / "state"
        self.native_state = self.root / "direct-state"
        self.native_state.mkdir()
        self.config_root.mkdir()
        self.state_root.mkdir()
        guard = self.item["target"]["site_id"].replace("#u12", "#u7")
        self.guard = guard
        weave = self.root / "weave.json"
        output = self.root / "woven"
        plan = self.root / "plan.jsonl"
        scope = self.root / "scope.jsonl"
        jar = self.root / "engine.jar"
        vm = self.root / "zero-vm" / "bin" / "java"
        put(vm, "reviewed Zero VM\n")
        put(plan, "one original task\n")
        put(scope, "one original scope\n")
        jar_sha = put(jar, "source built engine\n")
        put(weave, {"output_classes": str(output), "task_plan": str(plan)})
        receipt = output / "native-original-weave-receipt.json"
        receipt_sha = put(receipt, {"engine_jar": str(jar),
                                    "engine_jar_sha256": jar_sha})
        config = {
            "case_id": self.item["case_id"],
            "runner": {"mode": "concolic", "zero_vm_java": str(vm)},
            "junit": {"class": self.item["workload"]["test_class"],
                      "method": self.item["workload"]["test_method"]},
            "target_site": guard + "#1",
            "target_throw": {
                "siteId": self.item["target"]["site_id"],
                "exceptionClass": self.item["target"]["target_exception"]},
            "native_weave_config": str(weave),
            "recording": {"target_occurrence": "test/address",
                          "static_scope_map": str(scope)},
        }
        self.config_path = self.root / "original-case.json"
        config_sha = put(self.config_path, config)
        occurrence = self.root / "occurrence.json"
        occurrence_sha = put(occurrence, {"checkSiteId": guard,
                                          "reachedEventCount": 1,
                                          "selectedOccurrenceAddress": "test/address"})
        proof = self.root / "proof.json"
        put(proof, {
            "schema_version": 1, "mode": "original_graphchecker_native_adapter",
            "case_id": self.item["case_id"], "junit": config["junit"],
            "original_cluster_junit_verified": True,
            "recording_closed": True,
            "scope_generated_by_original_graphchecker": True,
            "source_evidence_paths": [str(source)],
            "target_occurrence_receipt_path": str(occurrence),
            "target_occurrence_receipt_sha256": occurrence_sha,
            "target_identity": {
                "original_guard_site_id": guard,
                "original_throw_site_id": self.item["target"]["site_id"],
                "inventory_throw_site_id": self.item["target"]["site_id"],
                "original_throw_source_line": self.item["target"]["source_line"],
                "exception_class": self.item["target"]["target_exception"]}})
        admission = self.root / "admission.json"
        put(admission, {"schema_version": 1,
                        "recording_fingerprint": {
                            "weave_config_sha256": hashlib.sha256(
                                weave.read_bytes()).hexdigest(),
                            "weave_receipt_sha256": receipt_sha,
                            "engine_jar_sha256": jar_sha},
                        "origin": {"selected_task_plan_sha256": hashlib.sha256(
                            plan.read_bytes()).hexdigest(),
                                   "static_scope_map_sha256": hashlib.sha256(
                                       scope.read_bytes()).hexdigest()}})
        stdout = self.root / "admission.stdout"
        put(stdout, f"ADMISSION_OK {self.config_path}\n")
        self.evidence = {"adapter_proof": proof,
                         "recording_admission": admission,
                         "validation_stdout": stdout}
        source_root = self.root / "frozen-source"
        put(source_root / "Mallory/native_graphchecker_campaign/campaign.py",
            "# frozen campaign\n")
        put(source_root / "Mallory/native_graphchecker_feedback/NativeFeedbackMain.java",
            "class NativeFeedbackMain {}\n")
        source_tar = self.root / "frozen-source.tar"
        with tarfile.open(source_tar, "w") as tar_stream:
            tar_stream.add(source_root / "Mallory", arcname="Mallory")
        self.source_pin = {"campaign_python_root": source_root,
                           "campaign_python_tar": source_tar}
        with patch("Mallory.native_graphchecker_queue.bind_and_run._validate_config"):
            binding = binding_for(self.item, self.config_path,
                                  self.native_state,
                                  target_source_archive=source_archive,
                                  **self.evidence, **self.source_pin)
        self.binding_path = self.config_root / "ZOOKEEPER-03.json"
        put(self.binding_path, binding)
        put(self.native_state / "checkpoint.json", {
            "schema_version": 1, "case_id": self.item["case_id"],
            "config_sha256": config_sha, "terminal": False,
            "status": "running", "completed_fault_trials": 2,
            "elapsed_seconds": 17.5})

    def test_direct_admission_resumes_existing_checkpoint_without_prep(self) -> None:
        self.assertFalse(self.config_path.with_suffix(".prep.json").exists())
        self.assertEqual(_native_case_files(self.item, self.config_root,
                                            self.state_root),
                         (self.config_path, self.native_state))
        with patch("Mallory.native_graphchecker_dispatch.checklist.native._validate_config"):
            row = inspect_case(self.item, "node0", self.config_root,
                               self.state_root)
        self.assertEqual(row["terminal_disposition"], "resumable")
        self.assertEqual(row["fault_trials"], 2)

    def test_shared_archived_source_supports_remote_host(self) -> None:
        (self.root / "Target.java").unlink()
        self.assertEqual(_native_case_files(self.item, self.config_root,
                                            self.state_root)[0], self.config_path)
        (self.root / "shared" / "Target.java").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "source differs"):
            _native_case_files(self.item, self.config_root, self.state_root)

    def test_concolic_source_tar_requires_feedback_java(self) -> None:
        java = (self.source_pin["campaign_python_root"] /
                "Mallory/native_graphchecker_feedback/NativeFeedbackMain.java")
        java.unlink()
        with patch("Mallory.native_graphchecker_queue.bind_and_run._validate_config"):
            with self.assertRaisesRegex(ValueError, "lacks NativeFeedbackMain"):
                binding_for(self.item, self.config_path, self.native_state,
                            target_source_archive=self.root / "shared/Target.java",
                            **self.evidence, **self.source_pin)

    def test_changed_admission_and_target_source_fail_closed(self) -> None:
        for path in (self.evidence["validation_stdout"],
                     self.root / "Target.java"):
            old = path.read_bytes()
            path.write_bytes(old + b"changed")
            with self.assertRaises(ValueError):
                _native_case_files(self.item, self.config_root, self.state_root)
            path.write_bytes(old)


if __name__ == "__main__":
    unittest.main()
