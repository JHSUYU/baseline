"""Pure receipt selection tests; no ZooKeeper process or Soot scan."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch import checklist
from Mallory.native_graphchecker_dispatch import preparation
from Mallory.native_graphchecker_dispatch import zookeeper_native_adapter as zk


class ZooKeeperNativeAdapterTest(unittest.TestCase):
    def test_inventory_throw_is_source_selected_not_hand_declared_io(self) -> None:
        cases, _ = checklist.load_inventory(checklist.DEFAULT_INVENTORY)
        row = next(case for case in cases if case["case_id"] == "ZOOKEEPER-07")
        request = preparation.build_request(row, checklist.DEFAULT_INVENTORY)
        self.assertEqual(("org.apache.zookeeper.server.quorum.Learner",
                          "registerWithLeader", 528), zk._target(request))
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
