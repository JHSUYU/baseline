"""The HDFS-40 v15 inventory amendment leaves v14 evidence immutable."""

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .inventory_epoch import (BASE_SHA256, EFFECTIVE_SHA256, LEGACY_CASE_IDS,
                              freeze_epoch_receipt,
                              load_queue_inventory)
from .results import export_native_results
from .stage_v15 import stage_v15
from .queue import run_worker


BASE = Path(__file__).resolve().parents[1] / "cases/inventory.json"


class InventoryEpochTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.base = self.root / "inventory-v14.json"
        self.base.write_bytes(BASE.read_bytes())
        old = json.loads(self.base.read_text())
        corrected = copy.deepcopy(old)
        row = next(row for row in corrected["cases"] if row["case_id"] == "HDFS-40")
        old_mapping = row["target"]["runtime_mapping"]["check_sites"][0]
        new_mapping = old_mapping.rsplit("@", 1)[0] + "@137:branch:14"
        row["target"]["runtime_mapping"]["check_sites"] = [new_mapping]
        self.corrected = self.root / "inventory-v15-effective.json"
        self.corrected.write_text(json.dumps(corrected, indent=2,
                                             ensure_ascii=False) + "\n")
        self.assertEqual(BASE_SHA256, self._sha(self.base))
        self.assertEqual(EFFECTIVE_SHA256, self._sha(self.corrected))
        self.assertEqual(BASE_SHA256, self._sha(BASE))
        old_rows = {row["case_id"]: row for row in old["cases"]}
        self.table = self.root / "results/native-102-results.json"
        self.table.parent.mkdir()
        result_rows = []
        for case_id in sorted(LEGACY_CASE_IDS):
            path = (self.state / ".native-queue" / "completions" /
                    f"{case_id}.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "case_id": case_id,
                "method": "original_native_graphchecker_campaign",
                "native_tested_complete": True}) + "\n")
        for case_id in old_rows:
            path = (self.state / ".native-queue" / "completions" /
                    f"{case_id}.json")
            terminal = path.is_file()
            result_rows.append({"case_id": case_id,
                                "native_state": ("verified_terminal" if terminal
                                                 else "pending"),
                                "completion_receipt_sha256": (self._sha(path)
                                                               if terminal else None)})
        self.table.write_text(json.dumps({"schema_version": 1,
                                          "inventory_sha256": BASE_SHA256,
                                          "verified_terminal_count": 18,
                                          "rows": result_rows}) + "\n")
        self.receipt = self.root / "epoch.json"
        self.document = freeze_epoch_receipt(self.base, self.state, self.table)
        self.assertEqual(old_mapping, self.document["old_mapping"])
        self.assertEqual(new_mapping, self.document["new_mapping"])
        self._write_receipt()

    @staticmethod
    def _sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_receipt(self):
        self.receipt.write_text(json.dumps(self.document, indent=2) + "\n")
        return self._sha(self.receipt)

    def _load(self, pin=None):
        return load_queue_inventory(self.base, self.state, self.receipt,
                                    pin or self._sha(self.receipt))

    def test_repository_inventory_keeps_v14_global_sha(self):
        before = BASE.read_bytes()
        self.assertEqual(BASE_SHA256, hashlib.sha256(before).hexdigest())
        self.assertIn(b"@131:branch:12", before)
        self.assertNotIn(b"@137:branch:14", before)
        self._load()
        self.assertEqual(before, BASE.read_bytes())
        self.assertEqual(BASE_SHA256, self._sha(BASE))

    def test_only_hdfs40_uses_corrected_guard_and_old_files_are_untouched(self):
        old_sha = self._sha(self.base)
        completed_before = {entry["case_id"]: self._sha(
            self.state / ".native-queue" / "completions" /
            f"{entry['case_id']}.json") for entry in self.document[
                "legacy_completions"]}
        original, _, no_epoch = load_queue_inventory(self.base, self.state)
        effective, systems, epoch = self._load()
        self.assertIsNone(no_epoch)
        self.assertEqual(102, len(effective))
        self.assertEqual(102, len(systems))
        self.assertEqual("HDFS-40", epoch["amended_case_id"])
        self.assertEqual(EFFECTIVE_SHA256, epoch["effective_inventory_sha256"])
        changes = [(a["case_id"], a, b) for a, b in zip(original, effective)
                   if a != b]
        self.assertEqual(["HDFS-40"], [case_id for case_id, _, _ in changes])
        self.assertTrue(changes[0][1]["target"]["runtime_mapping"][
            "check_sites"][0].endswith("@131:branch:12"))
        self.assertTrue(changes[0][2]["target"]["runtime_mapping"][
            "check_sites"][0].endswith("@137:branch:14"))
        self.assertEqual(old_sha, self._sha(self.base))
        self.assertEqual(completed_before, {case_id: self._sha(
            self.state / ".native-queue" / "completions" / f"{case_id}.json")
            for case_id in completed_before})

    def test_rejects_missing_or_tampered_epoch_and_completed_receipt(self):
        with self.assertRaisesRegex(ValueError, "exact SHA-256"):
            load_queue_inventory(self.base, self.state, self.receipt, "0" * 64)
        self.document["new_mapping"] = self.document["old_mapping"]
        self._write_receipt()
        with self.assertRaisesRegex(ValueError, "exact HDFS-40 guard"):
            self._load()
        self.document["new_mapping"] = (self.document["old_mapping"].rsplit(
            "@", 1)[0] + "@137:branch:14")
        self._write_receipt()
        case_id = self.document["legacy_completions"][0]["case_id"]
        path = (self.state / ".native-queue" / "completions" /
                f"{case_id}.json")
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "legacy completion pin changed"):
            self._load()

    def test_epoch_export_is_separate_and_records_both_inventory_hashes(self):
        pin = self._sha(self.receipt)
        (self.root / "ownership.json").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "cannot overwrite"):
            export_native_results(self.base, self.root / "ownership.json",
                                  self.root / "config", self.state,
                                  self.root / "results", self.receipt, pin)
        with mock.patch("Mallory.native_graphchecker_queue.results.native_rows",
                        return_value=[]):
            json_path, tsv_path = export_native_results(
                self.base, self.root / "ownership.json", self.root / "config",
                self.state, self.root / "results-v15", self.receipt, pin)
            old_json, old_tsv = export_native_results(
                self.base, self.root / "ownership.json", self.root / "config",
                self.state, self.root / "results-v14-fixture")
        document = json.loads(json_path.read_text())
        self.assertEqual(2, document["schema_version"])
        self.assertEqual(BASE_SHA256, document["inventory_sha256"])
        self.assertEqual(EFFECTIVE_SHA256, document[
            "inventory_epoch"]["effective_inventory_sha256"])
        self.assertIn("inventory_row_sha256", tsv_path.read_text())
        self.assertEqual(1, json.loads(old_json.read_text())["schema_version"])
        self.assertNotIn("inventory_epoch", json.loads(old_json.read_text()))
        self.assertNotIn("inventory_row_sha256", old_tsv.read_text())

    def test_stage_v15_copies_small_controls_without_editing_v14(self):
        old = self.root / "v14"
        new = self.root / "native-102-queue-v15-test"
        inventory = (old / "python-snapshot-bind-v14" / "Mallory" /
                     "cases/inventory.json")
        inventory.parent.mkdir(parents=True)
        shutil.copyfile(self.base, inventory)
        shutil.copytree(self.state, old / "state")
        (old / "results").mkdir()
        shutil.copyfile(self.table, old / "results/native-102-results.json")
        for relative in ("config/ownership.json", "config/HDFS-11.json",
                         "evidence/isolation.json",
                         "state/.native-queue/pilot-ZOOKEEPER-07.json"):
            path = old / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n")
        controller = old / "state/.native-queue/controllers/node0.json"
        controller.parent.mkdir(parents=True, exist_ok=True)
        controller.write_text('{"status":"running"}\n')
        with self.assertRaisesRegex(ValueError, "controller must stop"):
            stage_v15(old, new)
        self.assertFalse(new.exists())
        controller.write_text('{"status":"finished"}\n')
        before = {str(p.relative_to(old)): self._sha(p)
                  for p in old.rglob("*.json")}
        receipt = stage_v15(old, new)
        self.assertEqual("staged_no_junit_or_fault_trial", receipt["status"])
        self.assertEqual(BASE_SHA256, self._sha(new /
            "python-snapshot-bind-v4/Mallory/cases/inventory.json"))
        self.assertTrue((new / "pilot-v15.json").is_file())
        self.assertTrue((new / "inventory-epoch-receipt.json").is_file())
        self.assertFalse((new / "results/native-102-results.json").exists())
        self.assertEqual(before, {str(p.relative_to(old)): self._sha(p)
                                  for p in old.rglob("*.json")})
        with self.assertRaisesRegex(ValueError, "fresh isolated"):
            stage_v15(old, new)

    def test_handoff_freezes_new_terminal_without_revising_initial_18(self):
        extra = "ZOOKEEPER-06"
        path = self.state / ".native-queue/completions" / f"{extra}.json"
        path.write_text(json.dumps({"case_id": extra,
                                    "method": "original_native_graphchecker_campaign",
                                    "native_tested_complete": True}) + "\n")
        table = json.loads(self.table.read_text())
        row = next(row for row in table["rows"] if row["case_id"] == extra)
        row["native_state"] = "verified_terminal"
        row["completion_receipt_sha256"] = self._sha(path)
        table["verified_terminal_count"] = 19
        self.table.write_text(json.dumps(table) + "\n")
        frozen = freeze_epoch_receipt(self.base, self.state, self.table)
        self.assertEqual(19, frozen["legacy_terminal_count"])
        self.assertEqual(LEGACY_CASE_IDS | {extra},
                         {entry["case_id"] for entry in frozen["legacy_completions"]})
        prior = {entry["case_id"]: entry for entry in
                 self.document["legacy_completions"]}
        self.assertEqual(prior, {entry["case_id"]: entry for entry in
                                 frozen["legacy_completions"] if entry["case_id"]
                                 in LEGACY_CASE_IDS})
        self.document = frozen
        self._write_receipt()
        _, _, epoch = self._load()
        self.assertEqual(19, epoch["legacy_terminal_count"])
        self.assertIn(extra, epoch["legacy_case_ids"])

    def test_worker_does_not_reissue_v14_completion_from_copied_v15_binding(self):
        case_id = "HDFS-28"
        item = {"case_id": case_id, "system": "HDFS"}
        config = self.root / "config"
        config.mkdir()
        (config / f"{case_id}.json").write_text("{}\n")
        isolation = self.root / "isolation.json"
        isolation.write_text("{}\n")
        terminal = {"terminal_disposition": "tested_no_target_throw"}
        with (mock.patch("Mallory.native_graphchecker_queue.queue.physical_host"),
              mock.patch("Mallory.native_graphchecker_queue.queue.load_queue_inventory",
                         return_value=([item], {case_id: "HDFS"},
                                       {"epoch": "native-102-v15-hdfs40",
                                        "legacy_case_ids": [case_id]})),
              mock.patch("Mallory.native_graphchecker_queue.queue.load_ownership",
                         return_value={case_id: "node0"}),
              mock.patch("Mallory.native_graphchecker_queue.queue.load_reviews",
                         return_value={}),
              mock.patch("Mallory.native_graphchecker_queue.queue._native_case_files",
                         return_value=(config / f"{case_id}.json",
                                       self.root / "native")),
              mock.patch("Mallory.native_graphchecker_queue.queue._cached_terminal_inspection",
                         return_value=terminal),
              mock.patch("Mallory.native_graphchecker_queue.queue.validate_isolation"),
              mock.patch("Mallory.native_graphchecker_queue.queue.completion") as complete,
              mock.patch("Mallory.native_graphchecker_queue.queue._publish_results_if_requested") as publish):
            result = run_worker(
                host="node0", slot=0, slots=1, inventory=self.base,
                ownership_file=self.root / "ownership.json",
                config_root=config, state_root=self.state,
                scratch_root=self.root / "scratch", isolation_file=isolation,
                epoch_receipt=self.receipt,
                epoch_receipt_sha256=self._sha(self.receipt))
        self.assertEqual(0, result["completed"])
        complete.assert_not_called()
        publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
