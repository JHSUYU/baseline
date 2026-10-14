"""The shared ZooKeeper recipe pins every nested input before scheduling."""

import json
import tempfile
import unittest
from pathlib import Path

from Mallory.native_graphchecker_dispatch import build_zookeeper_recipe as builder
from Mallory.native_graphchecker_dispatch import preparation


class BuildZooKeeperRecipeTest(unittest.TestCase):
    def test_recipe_pins_gate_source_classpaths_and_original_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def file(name: str, data: str = "pin") -> str:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data, encoding="utf-8")
                return str(path)
            def classes(name: str) -> str:
                return str(Path(file(name + "/Target.class")).parent)

            source = file("source/Target.java")
            source_root = str(Path(source).parent)
            original = classes("original")
            postweave = classes("postweave")
            session = file("session/manifest.json", "{}")
            adapter = classes("adapter")
            verifier = classes("verifier")
            gate_file = root / "protocol-gate.json"
            gate = {
                "mode": "original_graphchecker_zookeeper_protocol_gate",
                "accepted": True, "typed_wire_send_receive": True,
                "junitPassed": True, "blockingGaps": 0,
                "typedWirePorts": ["ZOOKEEPER_QUORUM_HANDSHAKE#REQUEST"],
                "session_dir_path": str(Path(session).parent),
                "postweave_class_tree_path": postweave,
                "adapter_build_path": adapter,
                "session_reader_verifier_artifact_path": verifier,
                "session_reader_verifier_source_path": file("verifier.java"),
                "session_reader_receipt_path": file("session-reader.json", "{}"),
                "static_map_path": file("scope.jsonl"),
                "healthy_stdout_path": file("healthy.stdout"),
                "healthy_trace_manifest_path": file("trace-manifest.json", "{}"),
            }
            gate_file.write_text(json.dumps(gate), encoding="utf-8")
            profile_file = root / "zookeeper-profile.json"
            profile = {
                "mode": "original_graphchecker_zookeeper_profile",
                "protocol_gate": str(gate_file),
                "java": file("java"), "source_root": source_root,
                "source_classes": original,
                "communication_mapping": file("mapping.jsonl"),
                "analysis_classpath": [original],
                "scope_planner_classpath": [file("scope.jar")],
                "runtime_classpath": [file("runtime.jar")],
                "runner_classpath": [file("runner.jar")],
                "post_weave_classpath": [file("post.jar")],
            }
            profile_file.write_text(json.dumps(profile), encoding="utf-8")
            inventory = Path(file("inventory.json", "{}"))
            output = root / "recipes.json"
            document = builder.build(profile_file, inventory, output)
            recipe = preparation.load_recipes(output, inventory)["zookeeper"]
            self.assertEqual(document["systems"]["zookeeper"], recipe)
            self.assertNotIn("TARGET", json.dumps(recipe["argv"]))
            self.assertEqual(1, recipe["argv"].count("{request}"))
            self.assertIn(str(Path(session).parent), recipe["source_tree_pins"])
            self.assertIn(postweave, recipe["class_tree_pins"])
            self.assertIn(gate["static_map_path"], recipe["mapping_pins"])
            self.assertIn(profile["runtime_classpath"][0], recipe["classpath_pins"])
            Path(profile["runtime_classpath"][0]).write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed native classpath pin"):
                preparation.load_recipes(output, inventory)


if __name__ == "__main__":
    unittest.main()
