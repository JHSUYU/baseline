import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import guarded_phase_v17 as phase


class GuardedPhaseTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.pg0, self.output, self.raw, self.work = (root / x for x in
                                                     ("pg0", "output", "raw", "work"))
        for path in (self.pg0, self.output, self.raw, self.work):
            path.mkdir()
        self.config = root / "config.json"
        self.config.write_text(json.dumps({"case_id": "SUCCESSOR", "runner": {
            "local_artifact_root": str(self.raw), "local_work_root": str(self.work)}}))
        self.args = argparse.Namespace(
            mode="admit", pg0=self.pg0, config=self.config, output=self.output,
            raw_root=self.raw, receipt=root / "phase-receipt.json",
            config_sha256="pin", campaign_source_sha256="pin",
            max_raw_bytes=1000, max_output_bytes=1000,
            min_raw_available_bytes=0, min_output_available_bytes=0,
            min_root_available_bytes=0, min_memory_available_bytes=0,
            max_wall_seconds=60, poll_seconds=1,
            allow_frozen_healthy_seed=False)
        self.safe = {"raw_added_bytes": 0, "output_allocated_bytes": 0,
                     "raw_available_bytes": 2000, "output_available_bytes": 2000,
                     "root_available_bytes": 2000, "memory_available_bytes": 2000}

    def test_admission_does_not_create_checkpoint(self):
        class Done:
            def __init__(inner, command, **kwargs):
                self.assertEqual("--admit-only", command[-1])
                (self.output / "recording-admission.json").write_text("{}")

            def poll(inner): return 0
            def wait(inner): return 0

        with (patch.object(phase, "_require_pg0_read_only"),
              patch.object(phase, "_require_local", side_effect=lambda p, *_: p),
              patch.object(phase.campaign, "_validate_config"),
              patch.object(phase, "_sha", return_value="pin"),
              patch.object(phase, "_sample", return_value=self.safe),
              patch.object(phase.subprocess, "Popen", side_effect=Done)):
            receipt = phase.run(self.args)
        self.assertEqual("accepted", receipt["status"])
        self.assertFalse((self.output / "checkpoint.json").exists())

    def test_import_needs_cached_admission_before_child(self):
        self.args.mode = "import"
        with (patch.object(phase, "_require_pg0_read_only"),
              patch.object(phase, "_require_local", side_effect=lambda p, *_: p),
              patch.object(phase.campaign, "_validate_config"),
              patch.object(phase, "_sha", return_value="pin"),
              patch.object(phase.subprocess, "Popen") as popen):
            with self.assertRaisesRegex(ValueError, "sealed recording admission"):
                phase.run(self.args)
            popen.assert_not_called()

    def test_import_creates_only_pinned_checkpoint(self):
        self.args.mode = "import"
        (self.output / "recording-admission.json").write_text("{}")

        class Done:
            def __init__(inner, command, **kwargs):
                self.assertEqual("--import-only", command[-1])
                receipt = {"source_kind": "bounded_prefix_snapshot_v1",
                           "source_completed_fault_trials": 16}
                (self.output / "predecessor-import.json").write_text(json.dumps(receipt))
                (self.output / "checkpoint.json").write_text(json.dumps({
                    "case_id": "SUCCESSOR", "healthy": None, "trials": [], "active": None,
                    "completed_fault_trials": 0, "imported_completed_fault_trials": 16,
                    "predecessor_import": receipt}))

            def poll(inner): return 0
            def wait(inner): return 0

        with (patch.object(phase, "_require_pg0_read_only"),
              patch.object(phase, "_require_local", side_effect=lambda p, *_: p),
              patch.object(phase.campaign, "_validate_config"),
              patch.object(phase, "_sha", return_value="pin"),
              patch.object(phase, "_sample", return_value=self.safe),
              patch.object(phase.subprocess, "Popen", side_effect=Done)):
            receipt = phase.run(self.args)
        self.assertEqual("accepted", receipt["status"])
        self.assertEqual(0, json.loads((self.output / "checkpoint.json").read_text())[
            "completed_fault_trials"])

    def _frozen_fixture(self):
        trial = self.output / "trials" / "r0000"
        (trial / "iteration-native").mkdir(parents=True, exist_ok=True)
        graph = trial / "original-graph" / "anchor-00" / "summary.json"
        graph.parent.mkdir(parents=True, exist_ok=True)
        graph.write_text('{"edge": 1}')
        graph_sha = phase._sha(graph)
        summary = {"anchors": [{"occurrenceAddress": "dn0/region/one",
                                "summarySha256": graph_sha,
                                "summary": {"edge": 1}}]}
        result = {"status": "healthy_seed", "junit_passed": True,
                  "raw_exact_target_throw_count": 0,
                  "multi_anchor_addresses": ["dn0/region/one"]}
        (trial / "native-summary.json").write_text(json.dumps(summary))
        (trial / "result.json").write_text(json.dumps(result))
        (trial / "local-artifacts.json").write_text("{}")
        (trial / "iteration-native" / "fault-events.jsonl").write_text("")
        files = {str(p.relative_to(self.output)): phase._sha(p)
                 for p in trial.rglob("*") if p.is_file() and p != graph}
        frozen = {"source_healthy_files": files,
                  "source_graph_summaries": {
                      "original-graph/anchor-00/summary.json": graph_sha},
                  "source_healthy_result_sha256": files["trials/r0000/result.json"],
                  "source_native_summary_sha256": files[
                      "trials/r0000/native-summary.json"],
                  "source_raw_archive_sha256": "a" * 64}
        imported = {"source_kind": "bounded_prefix_snapshot_v1",
                    "source_completed_fault_trials": 16,
                    "frozen_healthy_seed": frozen}
        state = {"case_id": "SUCCESSOR", "healthy": {
            "name": "r0000", "status": "healthy_seed",
            "result": "trials/r0000/result.json"},
            "multi_anchor_addresses": ["dn0/region/one"],
            "imported_multi_anchor_addresses": ["dn0/region/one"],
            "trials": [], "active": None, "completed_fault_trials": 0,
            "imported_completed_fault_trials": 16,
            "predecessor_import": imported}
        config = {"recording": {"multi_target_max_anchors": 1},
                  "predecessor_campaign": {"frozen_healthy_seed": True}}
        return state, imported, config, graph

    def test_frozen_healthy_seed_requires_exact_graph_and_sidecars(self):
        state, imported, config, graph = self._frozen_fixture()
        self.assertTrue(phase._verified_frozen_healthy_seed(
            self.output, state, imported, config))
        graph.write_text('{"edge": 2}')
        self.assertFalse(phase._verified_frozen_healthy_seed(
            self.output, state, imported, config))

    def test_frozen_healthy_seed_rejects_unpinned_file_or_wrong_target(self):
        state, imported, config, _ = self._frozen_fixture()
        imported["frozen_healthy_seed"]["source_healthy_files"].pop(
            "trials/r0000/iteration-native/fault-events.jsonl")
        self.assertFalse(phase._verified_frozen_healthy_seed(
            self.output, state, imported, config))
        state, imported, config, _ = self._frozen_fixture()
        state["multi_anchor_addresses"] = ["different"]
        self.assertFalse(phase._verified_frozen_healthy_seed(
            self.output, state, imported, config))
        state, imported, config, _ = self._frozen_fixture()
        state["imported_multi_anchor_addresses"] = ["different"]
        self.assertFalse(phase._verified_frozen_healthy_seed(
            self.output, state, imported, config))
        state, imported, config, _ = self._frozen_fixture()
        config["predecessor_campaign"]["frozen_healthy_seed"] = False
        self.assertFalse(phase._verified_frozen_healthy_seed(
            self.output, state, imported, config))

    def test_import_accepts_only_opted_in_frozen_healthy_seed(self):
        self.args.mode = "import"
        self.args.allow_frozen_healthy_seed = True
        (self.output / "recording-admission.json").write_text("{}")
        self.config.write_text(json.dumps({"case_id": "SUCCESSOR", "runner": {
            "local_artifact_root": str(self.raw),
            "local_work_root": str(self.work)},
            "recording": {"multi_target_max_anchors": 1},
            "predecessor_campaign": {"frozen_healthy_seed": True}}))

        class Done:
            def __init__(inner, command, **kwargs):
                state, imported, _, _ = self._frozen_fixture()
                (self.output / "predecessor-import.json").write_text(json.dumps(imported))
                (self.output / "checkpoint.json").write_text(json.dumps(state))

            def poll(inner): return 0
            def wait(inner): return 0

        real_sha = phase._sha
        def pinned_sha(path):
            if Path(path) in (self.config, Path(phase.campaign.__file__)):
                return "pin"
            return real_sha(path)

        with (patch.object(phase, "_require_pg0_read_only"),
              patch.object(phase, "_require_local", side_effect=lambda p, *_: p),
              patch.object(phase.campaign, "_validate_config"),
              patch.object(phase, "_sha", side_effect=pinned_sha),
              patch.object(phase, "_sample", return_value=self.safe),
              patch.object(phase.subprocess, "Popen", side_effect=Done)):
            receipt = phase.run(self.args)
        self.assertEqual("accepted", receipt["status"])

    def test_admission_refuses_frozen_healthy_mode(self):
        self.args.allow_frozen_healthy_seed = True
        with self.assertRaisesRegex(ValueError, "only to import"):
            phase.run(self.args)


if __name__ == "__main__":
    unittest.main()
