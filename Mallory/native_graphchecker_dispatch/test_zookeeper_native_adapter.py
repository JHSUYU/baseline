"""Pure receipt selection tests; no ZooKeeper process or Soot scan."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch import checklist
from Mallory.native_graphchecker_dispatch import preparation
from Mallory.native_graphchecker_dispatch import zookeeper_native_adapter as zk


class ZooKeeperNativeAdapterTest(unittest.TestCase):
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
            source.write_text("source", encoding="utf-8")
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
            with patch.object(zk.subprocess, "run", side_effect=fresh_verifier):
                zk._rerun_session_reader(gate, Path("/usr/bin/java"))
            def changed_verifier(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
                Path(argv[-1]).write_text(json.dumps({**receipt,
                    "session_reader_incomplete": "missing rows"}), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0)
            with patch.object(zk.subprocess, "run", side_effect=changed_verifier):
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

    def test_inventory_throw_is_source_selected_not_hand_declared_io(self) -> None:
        cases, _ = checklist.load_inventory(checklist.DEFAULT_INVENTORY)
        row = next(case for case in cases if case["case_id"] == "ZOOKEEPER-07")
        request = preparation.build_request(row, checklist.DEFAULT_INVENTORY)
        self.assertEqual(("org.apache.zookeeper.server.quorum.Learner",
                          "registerWithLeader", 525), zk._target(request))
        self.assertNotIn("guard_source_lines", request["target"])
        self.assertNotIn("fault_sites", json.dumps(request))

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
