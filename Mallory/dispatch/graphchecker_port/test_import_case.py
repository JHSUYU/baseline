import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import Mallory.dispatch.graphchecker_port.import_case as import_module
from Mallory.dispatch.graphchecker_port.aggregate import (
    ReceiptReader, aggregate, load_import_index,
)
from Mallory.dispatch.graphchecker_port.import_case import import_case
from Mallory.dispatch.graphchecker_port.plan import sha256


INVENTORY = Path(__file__).parents[2] / "cases" / "inventory.json"


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


class ImportCaseTest(unittest.TestCase):
    def make_campaign(self, root: Path, selector: str, *, terminal: bool = True):
        config = root / "case.json"
        campaign = root / "campaign"
        trial = campaign / "trials" / "r0001"
        trial.mkdir(parents=True)
        _write(config, {"case_id": "HBASE-01", "junit": {
            "class": "example.TestCluster", "method": selector}})
        digest = sha256(config)
        for name in ("graphchecker-raw.jsonl", "graphchecker-trace.jsonl",
                     "graphchecker-graph.jsonl"):
            (trial / name).write_text("{}\n", encoding="utf-8")
        evidence_sha = sha256(trial / "graphchecker-raw.jsonl")
        result = {"backend": "graphchecker_native", "case_id": "HBASE-01",
                  "status": "checked", "fault_plan": [{"siteId": "io"}],
                  "elapsed_seconds": 2.25, "target_exception_triggered": False,
                  "target_exception_candidate": False, "junit_passed": True,
                  "evidence": {"strict_injection": True,
                               "post_fault_target_reached": True,
                               "injection_specific_target_reached": True,
                               "observed_check_sites": ["check"]},
                  "raw_trace_sha256": evidence_sha, "trace_sha256": evidence_sha,
                  "graph_sha256": evidence_sha}
        _write(trial / "result.json", result)
        record = {"name": "r0001", "result": "trials/r0001/result.json",
                  "status": "checked", "faults": result["fault_plan"],
                  "elapsed_seconds": 2.25, "strict_injection": True,
                  "post_fault_target_reached": True,
                  "injection_specific_target_reached": True,
                  "observed_check_sites": ["check"], "junit_passed": True,
                  "target_exception_triggered": False,
                  "target_exception_candidate": False}
        checkpoint = {"schema_version": 1, "case_id": "HBASE-01",
                      "config_sha256": digest,
                      "status": "complete_trial_budget" if terminal else "running",
                      "terminal": terminal, "completed_fault_trials": 1,
                      "trial_elapsed_seconds": 2.25, "trials": [record]}
        summary = {"schema_version": 1, "case_id": "HBASE-01",
                   "config_sha256": digest, "status": "complete_trial_budget",
                   "terminal": True, "completed_fault_trials": 1,
                   "trial_elapsed_seconds": 2.25, "strict_trials": 1,
                   "post_fault_target_trials": 1,
                   "target_exception_triggered_trials": 0,
                   "differential_candidates": 0}
        _write(campaign / "checkpoint.json", checkpoint)
        _write(campaign / "summary.json", summary)
        return config, campaign

    def test_terminal_import_keeps_prior_snapshot_and_aggregates_selected_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            first, first_campaign = self.make_campaign(root / "first", "first")
            first_receipt = import_case("HBASE-01", first, first_campaign, data)
            first_index = load_import_index(data / "import-index.json")
            first_snapshot = first_index["HBASE-01"]
            self.assertEqual(1, first_receipt["verified_native_trial_results"])
            self.assertEqual(first_receipt["source_sha256"]["config"],
                             sha256(first_snapshot / "config.json"))
            self.assertEqual(first_receipt["source_sha256"]["checkpoint"],
                             sha256(first_snapshot / "checkpoint.json"))
            self.assertEqual(1, import_case("HBASE-01", first, first_campaign,
                                            data)["verified_native_trial_results"])
            second, second_campaign = self.make_campaign(root / "second", "second")
            import_case("HBASE-01", second, second_campaign, data)
            imports = load_import_index(data / "import-index.json")
            self.assertNotEqual(first_snapshot, imports["HBASE-01"])
            self.assertTrue(first_snapshot.is_dir())
            rows = aggregate(INVENTORY, data / "configs", data / "cases",
                             ReceiptReader(data / "cases", remote=False,
                                           imports=imports), imports=imports)
            row = next(row for row in rows if row["case_id"] == "HBASE-01")
            self.assertEqual("example.TestCluster#second", row["junit_workload"])
            self.assertEqual("complete_trial_budget", row["receipt_status"])
            self.assertEqual(1, row["strict_trials"])
            self.assertEqual(str(imports["HBASE-01"] / "checkpoint.json"),
                             row["checkpoint_path"])

    def test_running_or_changed_artifact_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            config, campaign = self.make_campaign(root / "running", "test", terminal=False)
            with self.assertRaisesRegex(ValueError, "running campaign"):
                import_case("HBASE-01", config, campaign, data)
            self.assertFalse((data / "import-index.json").exists())
            config, campaign = self.make_campaign(root / "changed", "test")
            (campaign / "trials" / "r0001" / "graphchecker-raw.jsonl").write_text(
                "changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed legacy raw_trace"):
                import_case("HBASE-01", config, campaign, data)
            self.assertFalse((data / "import-index.json").exists())

    def test_index_rejects_changed_snapshot_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, campaign = self.make_campaign(root / "source", "test")
            data = root / "data"
            import_case("HBASE-01", config, campaign, data)
            selected = load_import_index(data / "import-index.json")["HBASE-01"]
            (selected / "summary.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                load_import_index(data / "import-index.json")

    def test_checkpoint_cannot_claim_strict_injection_absent_from_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, campaign = self.make_campaign(root / "source", "test")
            checkpoint = json.loads((campaign / "checkpoint.json").read_text())
            checkpoint["trials"][0]["strict_injection"] = False
            _write(campaign / "checkpoint.json", checkpoint)
            summary = json.loads((campaign / "summary.json").read_text())
            summary["strict_trials"] = 0
            _write(campaign / "summary.json", summary)
            with self.assertRaisesRegex(ValueError, "feedback differs"):
                import_case("HBASE-01", config, campaign, root / "data")

    def test_index_rejects_linked_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, campaign = self.make_campaign(root / "source", "test")
            data = root / "data"
            import_case("HBASE-01", config, campaign, data)
            selected = load_import_index(data / "import-index.json")["HBASE-01"]
            summary = selected / "summary.json"
            original = selected / "summary-original.json"
            summary.rename(original)
            summary.symlink_to(original.name)
            with self.assertRaisesRegex(ValueError, "symlink"):
                load_import_index(data / "import-index.json")

    def test_checkpoint_change_during_verification_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, campaign = self.make_campaign(root / "source", "test")
            verifier = import_module.verify_trial_artifacts

            def change_checkpoint(trial, result):
                verifier(trial, result)
                checkpoint = json.loads((campaign / "checkpoint.json").read_text())
                checkpoint["updated_at"] = "changed while verifying"
                _write(campaign / "checkpoint.json", checkpoint)

            with patch.object(import_module, "verify_trial_artifacts",
                              side_effect=change_checkpoint):
                with self.assertRaisesRegex(ValueError, "changed during"):
                    import_case("HBASE-01", config, campaign, root / "data")
            self.assertFalse((root / "data" / "import-index.json").exists())


if __name__ == "__main__":
    unittest.main()
