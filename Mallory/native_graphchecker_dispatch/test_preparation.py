"""Content-addressed native preparation tests; no Soot or JUnit execution."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.instrumentation.graphchecker_port.native_original_weave import (
    file_tree_digest,
)
from Mallory.native_graphchecker_dispatch import checklist, preparation as prep


class NativePreparationTest(unittest.TestCase):
    def test_stage_original_recording_artifacts_by_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original"
            original.mkdir()
            names = ("candidate_dataflow_edges.jsonl.gz",
                     "static_scope_map.jsonl", "region_skeletons.jsonl.gz")
            for index, name in enumerate(names):
                (original / name).write_bytes(bytes([index, 0, 255]))
            output = root / "recording-artifacts"
            receipt_path = root / "staging.json"
            receipt = prep.stage_original_recording_artifacts(
                original, output, receipt_path)
            for name in names:
                self.assertEqual((original / name).read_bytes(),
                                 (output / name).read_bytes())
                self.assertEqual(prep._sha(original / name),
                                 receipt["sidecar_sha256"][name])
            self.assertEqual(receipt, json.loads(receipt_path.read_text()))
            with self.assertRaisesRegex(ValueError, "absent"):
                prep.stage_original_recording_artifacts(original, output)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config_root = self.root / "configs"
        self.state_root = self.root / "states"
        self.config_root.mkdir()
        self.state_root.mkdir()
        self.inventory = checklist.DEFAULT_INVENTORY
        self.item = next(row for row in checklist.load_inventory(
            self.inventory)[0] if row["case_id"] == "HBASE-01")
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "Target.java").write_text("class Target {}\n")
        self.classpath = self.root / "classpath"
        self.classpath.mkdir()
        (self.classpath / "artifact.jar").write_bytes(b"original classes")
        self.mapping = self.root / "mapping.json"
        self.mapping.write_text('{"check":"HBASE-01"}\n')
        self.adapter = self.root / "adapter.py"
        self.adapter.write_text("# fixture native adapter\n")
        self.recipe_file = self.root / "recipes.json"
        self.write_recipe()

    def write_recipe(self) -> None:
        self.recipe = {
            "argv": ["python3", str(self.adapter), "{request}", "{output}"],
            "timeout_seconds": 30,
            "pins": {str(self.adapter): checklist._sha(self.adapter)},
            "source_tree_pins": {str(self.source): file_tree_digest(self.source)},
            "classpath_pins": {str(self.classpath): file_tree_digest(self.classpath)},
            "mapping_pins": {str(self.mapping): checklist._sha(self.mapping)},
        }
        self.recipe_file.write_text(json.dumps({
            "schema_version": 1,
            "inventory_sha256": checklist._sha(self.inventory),
            "systems": {"hbase": self.recipe},
        }, sort_keys=True))

    @staticmethod
    def engine() -> dict:
        return {"engine_jar_sha256": "a" * 64,
                "source_tree_sha256": "b" * 64,
                "dependency_artifacts": [{"sha256": "c" * 64}]}

    def test_request_is_inventory_derived_and_has_no_fault_doors(self) -> None:
        request = prep.build_request(self.item, self.inventory)
        self.assertEqual(self.item["target"]["site_id"],
                         request["target"]["site_id"])
        self.assertEqual(self.item["workload"]["selected_selector"],
                         request["original_junit"]["selector"])
        self.assertNotIn("door", json.dumps(request).lower())
        self.assertNotIn("io_points", json.dumps(request).lower())
        self.assertEqual(["hbase"], list(prep.load_recipes(
            self.recipe_file, self.inventory)))

    def test_same_inputs_reuse_static_and_both_weaves(self) -> None:
        invocations = []
        def adapter(_argv, _request, _output, attempt, _timeout):
            invocations.append("static + recording weave + concolic weave")
            prep._atomic(attempt / "exit.json", {"return_code": 0})
            return 0

        def promote(item, request, recipe_file, recipe, attempt,
                    case_root, config_root):
            return {"case_id": item["case_id"],
                    "cache_key": prep._cache_key(request, recipe, self.engine())}

        with patch.object(prep, "verify_engine", side_effect=self.engine), patch.object(
                prep, "_execute_adapter", side_effect=adapter), patch.object(
                prep, "_promote", side_effect=promote), patch.object(
                checklist, "verify_preparation_receipt", side_effect=lambda *_: {
                    "case_id": self.item["case_id"], "cache_key": prep._cache_key(
                        self._request(), self.recipe, self.engine())}), patch.object(
                prep, "_validate_output"):
            first = prep.prepare_one(self.item, self.inventory, self.recipe_file,
                                     self.recipe, self.config_root, self.state_root)
            second = prep.prepare_one(self.item, self.inventory, self.recipe_file,
                                      self.recipe, self.config_root, self.state_root)
        self.assertEqual("complete", first["status"])
        self.assertEqual(first, second)
        self.assertEqual(1, len(invocations))

    def _request(self) -> dict:
        request = prep.build_request(self.item, self.inventory)
        request["inventory_path"] = str(self.inventory.resolve(strict=True))
        return request

    def test_changed_source_or_engine_invalidates_closed_cache(self) -> None:
        with patch.object(prep, "verify_engine", side_effect=self.engine), patch.object(
                prep, "_execute_adapter", return_value=0), patch.object(
                prep, "_promote", return_value={"fixture": True}):
            prep.prepare_one(self.item, self.inventory, self.recipe_file,
                             self.recipe, self.config_root, self.state_root)
        (self.source / "Target.java").write_text("class Target { int x; }\n")
        with patch.object(prep, "verify_engine", side_effect=self.engine):
            with self.assertRaisesRegex(ValueError, "changed native source tree pin"):
                prep.prepare_one(self.item, self.inventory, self.recipe_file,
                                 self.recipe, self.config_root, self.state_root)
        (self.source / "Target.java").write_text("class Target {}\n")
        changed_engine = {**self.engine(), "engine_jar_sha256": "d" * 64}
        with patch.object(prep, "verify_engine", return_value=changed_engine):
            with self.assertRaisesRegex(ValueError, "inputs changed"):
                prep.prepare_one(self.item, self.inventory, self.recipe_file,
                                 self.recipe, self.config_root, self.state_root)

    def test_classpath_and_mapping_changes_reject_recipe(self) -> None:
        (self.classpath / "artifact.jar").write_bytes(b"changed classes")
        with self.assertRaisesRegex(ValueError, "changed native classpath pin"):
            prep.load_recipes(self.recipe_file, self.inventory)
        (self.classpath / "artifact.jar").write_bytes(b"original classes")
        self.mapping.write_text('{"check":"different"}\n')
        with self.assertRaisesRegex(ValueError, "changed native mapping pin"):
            prep.load_recipes(self.recipe_file, self.inventory)

    def test_failed_adapter_is_never_mistaken_for_prepared(self) -> None:
        with patch.object(prep, "verify_engine", side_effect=self.engine), patch.object(
                prep, "_execute_adapter", side_effect=lambda *_: 1), patch.object(
                prep, "_promote", return_value={}):
            state = prep.prepare_one(self.item, self.inventory, self.recipe_file,
                                     self.recipe, self.config_root, self.state_root)
        self.assertEqual("failed", state["status"])
        self.assertEqual("adapter", state["phase"])

    def test_interrupted_controller_adopts_closed_adapter_output(self) -> None:
        request = self._request()
        case_root = self.state_root / self.item["case_id"]
        prep_root = case_root / "preparation"
        prep_root.mkdir(parents=True)
        key = prep._cache_key(request, self.recipe, self.engine())
        attempt, _ = prep._new_attempt(prep_root, self.item, request,
                                       self.recipe, self.recipe_file, key)
        prep._atomic(attempt / "process.json", {"pid": 99999999,
                                                 "start_ticks": "1"})
        prep._atomic(attempt / "output/case.json", {"closed": True})
        prep._atomic(attempt / "output/adapter-proof.json", {"closed": True})
        with patch.object(prep, "verify_engine", side_effect=self.engine), patch.object(
                prep, "_execute_adapter", side_effect=AssertionError(
                    "must adopt closed output")), patch.object(
                prep, "_promote", return_value={"fixture": True}):
            result = prep.prepare_one(self.item, self.inventory, self.recipe_file,
                                      self.recipe, self.config_root, self.state_root)
        self.assertEqual("complete", result["status"])
        self.assertTrue(json.loads((attempt / "exit.json").read_text())[
            "recovered_from_closed_output"])


if __name__ == "__main__":
    unittest.main()
