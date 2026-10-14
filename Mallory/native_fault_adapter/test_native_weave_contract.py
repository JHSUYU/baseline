"""The fault manifest is pinned at weave time; trial admission is read only."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


WEAVER = (Path(__file__).resolve().parents[1] / "instrumentation" /
          "graphchecker_port" / "native_original_weave.py")
SPEC = importlib.util.spec_from_file_location("native_original_weave", WEAVER)
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


class NativeFaultWeaveContractTest(unittest.TestCase):
    def test_region_state_weaves_without_a_preexisting_concolic_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output, library, artifacts = (root / name for name in
                                                  ("source", "woven", "library", "recording"))
            for path in (source, library, artifacts):
                path.mkdir()
            (source / "Fixture.class").write_bytes(b"original")
            (library / "Library.class").write_bytes(b"dependency")
            (artifacts / "recording.jsonl").write_text('{"source":"original"}\n')
            skeletons = root / "regions.jsonl"
            skeletons.write_text('{"id":"region"}\n')
            java = root / "java"
            java.write_bytes(b"pinned java")
            engine = root / "engine.jar"
            engine.write_bytes(b"pinned engine")
            engine_receipt = root / "engine-receipt.json"
            engine_receipt.write_text('{}\n')
            config = {"weave_mode": "region_state",
                      "input_classes": str(source), "output_classes": str(output),
                      "region_skeletons": str(skeletons),
                      "recording_artifacts": str(artifacts),
                      "dependency_classpath": str(library), "java": str(java)}
            config_file = root / "weave.json"
            config_file.write_text(json.dumps(config))

            def weave(command, **_kwargs):
                self.assertFalse(any("causynth.concolic.task" in arg
                                     for arg in command))
                (output / "Fixture.class").write_bytes(b"woven")

            with patch.object(native, "JAR", engine), patch.object(
                    native, "ENGINE_RECEIPT", engine_receipt), patch.object(
                    native, "verify_engine", return_value={"dependency_classpath": ""}), patch.object(
                    native, "verified_vendor"), patch.object(
                    native.subprocess, "run", side_effect=weave):
                receipt = native.run(config_file)
                self.assertNotIn("task_id", receipt)
                self.assertNotIn("task_plan_sha256", receipt)
                self.assertEqual(receipt, native.verify_existing(config_file))
                changed = dict(config, task_id="fabricated")
                config_file.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "both task_plan and task_id"):
                    native.inputs(config_file)

    def test_pretrial_verification_pins_manifest_without_reweaving(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output, process, library = (root / name for name in
                                       ("source", "woven", "process", "library"))
            for path in (source, output, process, library):
                path.mkdir()
            (source / "Fixture.class").write_bytes(b"original")
            (output / "Fixture.class").write_bytes(b"woven")
            (process / "Extra.class").write_bytes(b"selected dependency")
            (library / "Other.class").write_bytes(b"library dependency")
            task = root / "task.jsonl"
            task.write_text('{"taskId":"recorded"}\n')
            skeletons = root / "regions.jsonl"
            skeletons.write_text('{"id":"region"}\n')
            manifest = root / "static-weave-manifest.json"
            manifest.write_text('{"doors":[],"targets":[]}\n')
            engine = root / "engine.jar"
            engine.write_bytes(b"pinned original engine")
            engine_receipt = root / "engine-receipt.json"
            engine_receipt.write_text('{}\n')
            java = root / "java"
            java.write_bytes(b"pinned java")
            config = {"input_classes": str(source),
                      "output_classes": str(output), "task_plan": str(task),
                      "task_id": "recorded", "region_skeletons": str(skeletons),
                      "dependency_classpath": str(library), "java": str(java),
                      "native_fault_manifest": str(manifest),
                      "process_dirs": [str(process)]}
            config_file = root / "weave.json"
            config_file.write_text(json.dumps(config))
            receipt = {
                "schema_version": 1,
                "mode": "mallory_vendored_original_graphchecker_concolic_weave",
                "upstream_revision": native.REVISION,
                "config_sha256": native.digest(config_file),
                "engine_jar_sha256": native.digest(engine),
                "engine_receipt_sha256": native.digest(engine_receipt),
                "task_plan_sha256": native.digest(task),
                "region_skeletons_sha256": native.digest(skeletons),
                "input_classes_sha256": native.class_tree_digest(source),
                "output_classes_sha256": native.class_tree_digest(output),
                "dependency_classpath_sha256": __import__("hashlib").sha256(
                    str(library).encode()).hexdigest(),
                "dependency_artifacts": native.dependency_digests(str(library)),
                "java_sha256": native.digest(java),
                "native_fault_manifest_sha256": native.digest(manifest),
                "process_dir_artifacts": native.dependency_digests(str(process)),
                "input_classes": str(source), "output_classes": str(output),
                "task_id": "recorded", "post_weave": None,
            }
            (output / "native-original-weave-receipt.json").write_text(
                json.dumps(receipt))
            with patch.object(native, "JAR", engine), patch.object(
                    native, "ENGINE_RECEIPT", engine_receipt), patch.object(
                    native, "verify_engine"), patch.object(
                    native, "verified_vendor"), patch.object(
                    native.subprocess, "run", side_effect=AssertionError(
                        "pretrial verification must never reweave")):
                self.assertEqual(receipt, native.verify_existing(config_file))
                manifest.write_text('{"doors":[{"siteId":"new"}],"targets":[]}\n')
                with self.assertRaisesRegex(ValueError,
                                            "native_fault_manifest_sha256"):
                    native.verify_existing(config_file)
                manifest.write_text('{"doors":[],"targets":[]}\n')
                (process / "Extra.class").write_bytes(b"changed dependency")
                with self.assertRaisesRegex(ValueError,
                                            "process_dir_artifacts"):
                    native.verify_existing(config_file)


if __name__ == "__main__":
    unittest.main()
