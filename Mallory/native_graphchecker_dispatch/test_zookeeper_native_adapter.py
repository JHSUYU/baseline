"""Pure receipt selection tests; no ZooKeeper process or Soot scan."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch import checklist
from Mallory.native_graphchecker_dispatch import preparation
from Mallory.native_graphchecker_dispatch import build_zookeeper_protocol_gate as gate_builder
from Mallory.native_graphchecker_dispatch import zookeeper_native_adapter as zk


class ZooKeeperNativeAdapterTest(unittest.TestCase):
    def test_recipe_cache_pins_nested_gate_session_and_classpaths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: str(root / name) for name in (
                "profile.json", "gate.json", "java", "source", "classes",
                "mapping.jsonl", "dependency.jar", "session", "postweave",
                "adapter-build", "verifier.jar", "verifier.java",
                "session-reader.json", "scope.jsonl", "healthy.stdout",
                "trace-manifest.json")}
            gate = {
                "session_dir_path": paths["session"],
                "postweave_class_tree_path": paths["postweave"],
                "adapter_build_path": paths["adapter-build"],
                "session_reader_verifier_artifact_path": paths["verifier.jar"],
                "session_reader_verifier_source_path": paths["verifier.java"],
                "session_reader_receipt_path": paths["session-reader.json"],
                "static_map_path": paths["scope.jsonl"],
                "healthy_stdout_path": paths["healthy.stdout"],
                "healthy_trace_manifest_path": paths["trace-manifest.json"],
            }
            profile = {
                "mode": zk.PROFILE_MODE,
                "protocol_gate": paths["gate.json"],
                "java": paths["java"],
                "source_root": paths["source"],
                "source_classes": paths["classes"],
                "communication_mapping": paths["mapping.jsonl"],
                "analysis_classpath": [paths["classes"], paths["dependency.jar"]],
                "scope_planner_classpath": [paths["dependency.jar"]],
                "runtime_classpath": [paths["dependency.jar"]],
                "runner_classpath": [paths["dependency.jar"]],
                "post_weave_classpath": [paths["dependency.jar"]],
            }
            Path(paths["gate.json"]).write_text(json.dumps(gate), encoding="utf-8")
            Path(paths["profile.json"]).write_text(json.dumps(profile), encoding="utf-8")
            recipe = {
                "argv": ["python3", "-m", "Mallory.native_graphchecker_dispatch.zookeeper_native_adapter",
                         paths["profile.json"], "{request}", "{output}"],
                "pins": {name: "pin" for name in (
                    paths["profile.json"], paths["gate.json"], paths["java"],
                    paths["session-reader.json"], paths["verifier.java"],
                    paths["healthy.stdout"], paths["trace-manifest.json"],
                    str(Path(zk.__file__).resolve()),
                    str(Path(zk.__file__).with_name(
                        "build_zookeeper_protocol_gate.py").resolve()),
                    str(Path(zk.__file__).with_name(
                        "NativeZooKeeperCombinedPostWeave.java").resolve()),
                    str(Path(zk.__file__).with_name(
                        "NativeZooKeeperSessionVerifier.java").resolve()))},
                "source_tree_pins": {paths["source"]: "pin", paths["session"]: "pin"},
                "class_tree_pins": {paths["classes"]: "pin",
                                    paths["postweave"]: "pin"},
                "mapping_pins": {paths["mapping.jsonl"]: "pin",
                                 paths["scope.jsonl"]: "pin"},
                "classpath_pins": {paths["dependency.jar"]: "pin",
                                   paths["adapter-build"]: "pin",
                                   paths["verifier.jar"]: "pin"},
            }
            preparation._audit_zookeeper_recipe_pins(recipe)
            del recipe["source_tree_pins"][paths["session"]]
            with self.assertRaisesRegex(ValueError, "session"):
                preparation._audit_zookeeper_recipe_pins(recipe)

    def test_session_gate_requires_pinned_session_reader_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "sessions" / "session-1"
            session.mkdir(parents=True)
            for name in zk.SESSION_FILES:
                (session / name).write_text("", encoding="utf-8")
            manifest = session / "manifest.json"
            manifest.write_text(json.dumps({"schemaVersion": 2,
                                            "kind": "SESSION_MANIFEST",
                                            "sessionId": "session-1",
                                            "role": "SEED",
                                            "closed": True}), encoding="utf-8")
            source = root / "Verifier.java"
            source.write_bytes(Path(zk.__file__).with_name(
                "NativeZooKeeperSessionVerifier.java").read_bytes())
            artifact = root / "verifier.jar"
            artifact.write_bytes(b"build")
            gate = {
                "session_dir_path": str(session),
                "session_tree_sha256": zk.weave.file_tree_digest(session),
                "session_manifest_path": str(manifest),
                "session_manifest_sha256": zk._sha(manifest),
                "engine_jar_sha256": "engine pin",
                "schedule_wire_sites": "TYPED_QUORUM#REQUEST",
                "session_reader_verifier_source_path": str(source),
                "session_reader_verifier_source_sha256": zk._sha(source),
                "session_reader_verifier_artifact_path": str(artifact),
                "session_reader_verifier_artifact_sha256": zk._sha(artifact),
            }
            with self.assertRaisesRegex(ValueError, "SessionReader proof"):
                zk._verify_closed_session(gate)
            receipt_path = root / "session-reader.json"
            receipt = {
                "mode": "original_session_reader_complete",
                "session_reader_incomplete": "",
                "session_role": "SEED",
                "schedule_wire_sites": gate["schedule_wire_sites"],
                "schedule_wire_pairs": 2,
                "schedule_pairing_gaps": 0,
                "gap_rows": 0,
                "session_dir_path": str(session),
                "session_tree_sha256": gate["session_tree_sha256"],
                "session_manifest_sha256": gate["session_manifest_sha256"],
                "engine_jar_sha256": gate["engine_jar_sha256"],
                "session_id": "session-1",
                "session_reader_verifier_source_sha256": gate[
                    "session_reader_verifier_source_sha256"],
                "session_reader_verifier_artifact_sha256": gate[
                    "session_reader_verifier_artifact_sha256"],
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            gate["session_reader_receipt_path"] = str(receipt_path)
            gate["session_reader_receipt_sha256"] = zk._sha(receipt_path)
            zk._verify_closed_session(gate)
            def fresh_verifier(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
                self.assertTrue(any(arg.endswith(".NativeZooKeeperSessionVerifier")
                                    for arg in argv))
                Path(argv[-1]).write_text(json.dumps(receipt), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0)
            with patch.object(zk.native, "JAR", Path("/usr/bin/java")), \
                    patch.object(zk, "_original_cp", return_value="fixture"), \
                    patch.object(zk.subprocess, "run", side_effect=fresh_verifier):
                zk._rerun_session_reader(gate, Path("/usr/bin/java"))
            def changed_verifier(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
                Path(argv[-1]).write_text(json.dumps({**receipt,
                    "session_reader_incomplete": "missing rows"}), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0)
            with patch.object(zk.native, "JAR", Path("/usr/bin/java")), \
                    patch.object(zk, "_original_cp", return_value="fixture"), \
                    patch.object(zk.subprocess, "run", side_effect=changed_verifier):
                with self.assertRaisesRegex(ValueError, "receipt changed"):
                    zk._rerun_session_reader(gate, Path("/usr/bin/java"))
            (session / "targets.jsonl").write_text("new row", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "session tree changed"):
                zk._verify_closed_session(gate)
            (session / "targets.jsonl").write_text("", encoding="utf-8")
            receipt["session_reader_incomplete"] = "decisions.jsonl unreadable"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            gate["session_reader_receipt_sha256"] = zk._sha(receipt_path)
            with self.assertRaisesRegex(ValueError, "did not close"):
                zk._verify_closed_session(gate)
            receipt["session_reader_incomplete"] = ""
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            gate["session_reader_receipt_sha256"] = zk._sha(receipt_path)
            source.write_text("unrelated verifier", encoding="utf-8")
            gate["session_reader_verifier_source_sha256"] = zk._sha(source)
            with self.assertRaisesRegex(ValueError, "verifier source differs"):
                zk._verify_closed_session(gate)

    def test_wire_gate_accepts_any_verified_transport_family(self) -> None:
        self.assertTrue(zk._valid_wire_ports(["CLIENT_REQUEST"]))
        self.assertTrue(zk._valid_wire_ports(["FOLLOWERINFO", "LEADERINFO"]))
        self.assertFalse(zk._valid_wire_ports([]))
        self.assertFalse(zk._valid_wire_ports(["CLIENT_REQUEST", "CLIENT_REQUEST"]))
        self.assertFalse(zk._valid_wire_ports([" CLIENT_REQUEST"]))
        capability = {"mode": zk.GATE_MODE, "accepted": True,
                      "typed_wire_send_receive": True, "junitPassed": True,
                      "blockingGaps": 0, "typedWirePorts": ["CLIENT_REQUEST"]}
        self.assertTrue(zk._reusable_gate_claims(capability))
        self.assertNotIn("targetSiteId", capability)
        self.assertNotIn("junitMethod", capability)
        self.assertFalse(zk._reusable_gate_claims({**capability,
                          "typed_wire_send_receive": False}))

    def test_original_streaming_manifest_uses_closed_status(self) -> None:
        manifest = Path(
            "/proj/silentfailure-PG0/ZhenyuLi/Mallory/"
            "ZOOKEEPER-07-20261013-native-wjtp-campaign-v4/campaign/"
            "trials/r0000/iteration-native/trace/streaming_trace_manifest.json")
        if not manifest.is_file():
            self.skipTest("pinned ZooKeeper recording unavailable")
        self.assertTrue(zk._closed_trace_manifest(json.loads(manifest.read_text())))
        self.assertFalse(zk._closed_trace_manifest({"kind": "STREAMING_RUNTIME_TRACE",
                                                    "status": "OPEN"}))

    def test_original_session_reader_verifies_zk07_wire_pairs(self) -> None:
        """Read an existing closed seed; do not start ZooKeeper or a campaign."""
        session = Path(
            "/proj/silentfailure-PG0/ZhenyuLi/Mallory/"
            "ZOOKEEPER-07-20261013-native-wjtp-campaign-v4/campaign/"
            "trials/r0000/iteration-native/sessions/iteration-native-d3832d30")
        engine = (Path("/users/ZhenyuLi/baseline/Mallory/") /
                  "static_scope_port/original_engine/target")
        jar = engine / "mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
        dependencies = engine / "native-original-dependencies.txt"
        if (not session.is_dir() or not jar.is_file() or
                not dependencies.is_file() or not shutil.which("javac")):
            self.skipTest("pinned original ZooKeeper seed or Java build unavailable")
        classpath = str(jar) + ":" + dependencies.read_text().strip()
        source = Path(zk.__file__).with_name("NativeZooKeeperSessionVerifier.java")
        with tempfile.TemporaryDirectory() as temporary:
            classes = Path(temporary) / "classes"
            classes.mkdir()
            subprocess.run(["javac", "-cp", classpath, "-d", str(classes),
                            str(source)], check=True, capture_output=True)
            receipt = Path(temporary) / "receipt.json"
            subprocess.run([
                "java", f"-Dcausynth.engine.jar={jar}",
                "-Dcausynth.typed.wire.sites=auto",
                "-cp", str(classes) + ":" + classpath,
                "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperSessionVerifier",
                str(session), str(receipt)], check=True, capture_output=True)
            proof = json.loads(receipt.read_text())
            self.assertEqual("", proof["session_reader_incomplete"])
            self.assertEqual("SEED", proof["session_role"])
            self.assertEqual(12, proof["schedule_wire_pairs"])
            self.assertEqual("ZOOKEEPER_QUORUM_HANDSHAKE#REQUEST",
                             proof["schedule_wire_sites"])
            self.assertEqual(0, proof["schedule_pairing_gaps"])
            self.assertEqual(0, proof["gap_rows"])
            self.assertEqual(zk.weave.file_tree_digest(session),
                             proof["session_tree_sha256"])
            changed = Path(temporary) / "sessions" / session.name
            shutil.copytree(session, changed)
            schedule = changed / "schedule.jsonl"
            rows = schedule.read_text().splitlines()
            for index, line in enumerate(rows):
                row = json.loads(line)
                if (row.get("site") == "ZOOKEEPER_QUORUM_HANDSHAKE#REQUEST"
                        and row.get("kind") == "SEND"):
                    row["endpoint"] = "unmatched-endpoint"
                    rows[index] = json.dumps(row)
                    break
            else:
                self.fail("verified seed lacks a wire SEND")
            schedule.write_text("\n".join(rows) + "\n")
            bad_receipt = Path(temporary) / "bad-receipt.json"
            subprocess.run([
                "java", f"-Dcausynth.engine.jar={jar}",
                "-Dcausynth.typed.wire.sites=auto",
                "-cp", str(classes) + ":" + classpath,
                "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperSessionVerifier",
                str(changed), str(bad_receipt)], check=True, capture_output=True)
            self.assertGreater(json.loads(bad_receipt.read_text())[
                "schedule_pairing_gaps"], 0)

    def test_reusable_gate_is_built_from_existing_zk07_seed(self) -> None:
        base = Path("/proj/silentfailure-PG0/ZhenyuLi/Mallory")
        v1 = base / "ZOOKEEPER-07-20261013-native-wjtp-campaign-v1"
        v4 = base / "ZOOKEEPER-07-20261013-native-wjtp-campaign-v4"
        engine = (Path("/users/ZhenyuLi/baseline/Mallory/") /
                  "static_scope_port/original_engine/target")
        jar = engine / "mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
        dependencies = engine / "native-original-dependencies.txt"
        session = (v4 / "campaign/trials/r0000/iteration-native/sessions/"
                   "iteration-native-d3832d30")
        if (not session.is_dir() or not jar.is_file() or
                not dependencies.is_file() or not shutil.which("javac")):
            self.skipTest("pinned original ZooKeeper seed or Java build unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gate_file = root / "gate.json"
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "schema_version": 1, "mode": zk.PROFILE_MODE,
                "system_version": "3.8.7", "protocol_gate": str(gate_file),
                "analysis": {},
                "source_root": "/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7",
                "source_classes": str(v1 / "inputs/classes/original"),
                "communication_mapping": str(v1 / "inputs/communication-mappings.jsonl"),
                "java": "/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java",
                "analysis_classpath": [str(v1 / "inputs/classes/original")],
                "scope_planner_classpath": [str(jar)],
                "runtime_classpath": [str(v1 / "inputs/classes/protocol")],
                "runner_classpath": [str(v1 / "inputs/classes/zk-test"),
                                     str(v1 / "inputs/classes/recording-harness")],
                "post_weave_classpath": [str(v1 / "inputs/classes/post-weave"),
                                         str(v1 / "inputs/classes/protocol"),
                                         str(v1 / "inputs/classes/actor")],
                "budget": {"fault_trials": 1, "seconds": 60,
                           "max_faults_per_trial": 2},
                "timeout_seconds": 120, "max_jobs": 10}))
            seed = root / "seed.json"
            seed.write_text(json.dumps({
                "session_dir_path": str(session),
                "healthy_stdout_path": str(v4 / "campaign/trials/r0000/stdout.log"),
                "healthy_trace_manifest_path": str(v4 / "campaign/trials/r0000/"
                                                    "iteration-native/trace/"
                                                    "streaming_trace_manifest.json"),
                "static_map_path": str(v1 / "inputs/static/static_scope_map.jsonl"),
                "postweave_class_tree_path": str(v4 / "inputs/classes/region-state-woven"),
                "adapter_build_path": str(v1 / "inputs/classes/protocol")}))
            with patch.object(zk.native, "JAR", jar), \
                    patch.object(zk.native, "DEPENDENCIES", dependencies):
                gate = gate_builder.build(profile, seed, gate_file)
                zk._verify_closed_session(gate)
                zk._rerun_session_reader(gate,
                    Path("/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java"))
                cases, _ = checklist.load_inventory(checklist.DEFAULT_INVENTORY)
                zk03 = next(row for row in cases if row["case_id"] == "ZOOKEEPER-03")
                request = preparation.build_request(zk03, checklist.DEFAULT_INVENTORY)
                self.assertEqual(zk.PROFILE_MODE,
                                 zk._profile(request, profile)["mode"])
            self.assertTrue(zk._reusable_gate_claims(gate))
            self.assertEqual(["ZOOKEEPER_QUORUM_HANDSHAKE#REQUEST"],
                             gate["typedWirePorts"])
            self.assertNotIn("targetSiteId", gate)
            self.assertNotIn("junitMethod", gate)

    def test_inventory_throw_is_source_selected_not_hand_declared_io(self) -> None:
        cases, _ = checklist.load_inventory(checklist.DEFAULT_INVENTORY)
        row = next(case for case in cases if case["case_id"] == "ZOOKEEPER-07")
        request = preparation.build_request(row, checklist.DEFAULT_INVENTORY)
        self.assertEqual(("org.apache.zookeeper.server.quorum.Learner",
                          "registerWithLeader", 525), zk._target(request))
        self.assertNotIn("guard_source_lines", request["target"])
        self.assertNotIn("fault_sites", json.dumps(request))

    def test_unstarted_zk03_uses_original_shared_junit_without_io_list(self) -> None:
        cases, _ = checklist.load_inventory(checklist.DEFAULT_INVENTORY)
        row = next(case for case in cases if case["case_id"] == "ZOOKEEPER-03")
        request = preparation.build_request(row, checklist.DEFAULT_INVENTORY)
        source = Path(row["provenance"]["source_root"])
        target = source / request["target"]["source_path"]
        junit = source / request["original_junit"]["source_path"]
        if not source.is_dir():
            self.skipTest("original ZooKeeper source unavailable")
        self.assertEqual(request["target"]["source_sha256"], zk._sha(target))
        self.assertIn(request["original_junit"]["method"] + "(",
                      junit.read_text(encoding="utf-8"))
        self.assertEqual("setOwner", zk._target(request)[1])
        self.assertEqual("org.apache.zookeeper.test.QuorumTest#testMultiToFollower",
                         request["original_junit"]["selector"])
        self.assertNotIn("fault_sites", json.dumps(request))
        self.assertNotIn("doors", json.dumps(request))

    def test_only_unique_admitted_original_target_task_is_selected(self) -> None:
        occurrence = {"selectedOccurrenceAddress": "peer/region/one",
                      "checkSiteId": "<pkg.Target: void check()>#u7"}
        match = {"goalKind": "TARGET_REACH_CLOSURE",
                 "occurrenceId": occurrence["selectedOccurrenceAddress"],
                 "targetBranch": {"siteId": occurrence["checkSiteId"],
                                  "occurrence": 2},
                 "admission": {"state": "EXECUTABLE"},
                 "taskId": "TASK.target"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "execution_task_plan.jsonl"
            other = {**match, "goalKind": "REGION_PATH_CLOSURE",
                     "taskId": "TASK.other"}
            path.write_text(json.dumps(other) + "\n" + json.dumps(match) + "\n")
            self.assertEqual("TASK.target", zk.select_target_task(
                path, occurrence)["taskId"])
            path.write_text(json.dumps(other) + "\n")
            with self.assertRaisesRegex(ValueError, "one exact target task"):
                zk.select_target_task(path, occurrence)
            path.write_text(json.dumps(match) + "\n" + json.dumps(match) + "\n")
            with self.assertRaisesRegex(ValueError, "one exact target task"):
                zk.select_target_task(path, occurrence)

    def test_unaccepted_protocol_gate_stops_before_static_or_junit(self) -> None:
        cases, _ = checklist.load_inventory(checklist.DEFAULT_INVENTORY)
        row = next(case for case in cases if case["case_id"] == "ZOOKEEPER-07")
        request = preparation.build_request(row, checklist.DEFAULT_INVENTORY)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            for key in (row["target"]["source_path"],
                        row["workload"]["test_source_path"]):
                original = Path(row["provenance"]["source_root"]) / key
                target = source / key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original.read_bytes())
            classes = root / "classes"
            classes.mkdir()
            (classes / "Fixture.class").write_bytes(b"class bytes")
            mapping = root / "mapping.jsonl"
            mapping.write_text("{}\n")
            java = root / "java"
            java.write_bytes(b"fixture binary")
            gate = root / "gate.json"
            gate.write_text(json.dumps({"mode": zk.GATE_MODE,
                                        "accepted": False}))
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "schema_version": 1, "mode": zk.PROFILE_MODE,
                "system_version": "3.8.7", "source_root": str(source),
                "source_classes": str(classes),
                "communication_mapping": str(mapping), "java": str(java),
                "protocol_gate": str(gate), "analysis": {},
                "analysis_classpath": [str(classes)],
                "scope_planner_classpath": [str(classes)],
                "runtime_classpath": [str(classes)],
                "runner_classpath": [str(classes)],
                "post_weave_classpath": [str(classes)],
                "budget": {"fault_trials": 1, "seconds": 10,
                           "max_faults_per_trial": 2},
                "max_jobs": 1, "timeout_seconds": 10,
            }))
            request_file = root / "request.json"
            request_file.write_text(json.dumps(request))
            with patch.object(zk, "_run", side_effect=AssertionError(
                    "no heavy stage before protocol gate")):
                with self.assertRaisesRegex(ValueError, "protocol gate pending"):
                    zk.prepare(request_file, root / "output", profile)
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
