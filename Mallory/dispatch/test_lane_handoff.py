"""Regression checks for durable lane handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from Mallory.dispatch import lane_handoff


class LaneHandoffTest(unittest.TestCase):
    def test_case_disk_estimate_is_forwarded_to_scheduler(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = lane_handoff.one_case_command(
                repo=root, state_root=root / "state", data_root=root / "data",
                case_id="HDFS-22", system="hdfs", config_path=root / "config.json",
                inventory=root / "inventory.json", source_reference=root / "reference.json",
                hosts_file=root / "hosts.json", release_manifest=root / "manifest.json",
                lane_id="hdfs-lane2", case_estimate_gib=1.5)
            self.assertEqual("1.5", command[command.index("--remote-case-gib") + 1])
            self.assertEqual({"schema_version": 1, "cases": [{"case_id": "HDFS-22",
                                                             "system": "hdfs"}]},
                             json.loads((root / "state/handoff/HDFS-22.json").read_text()))

    def test_pinned_ownership_offload_is_case_specific(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "ownership.json"
            inventory = root / "inventory.json"
            reference = root / "source-reference.json"
            revision_path = root / "revision.json"
            base.write_text(json.dumps({"owner": {"HDFS-25": "node0",
                                                   "HDFS-27": "node0",
                                                   "HDFS-28": "node0"}}))
            inventory.write_text("{}")
            reference.write_text("{}")
            revision = {
                "schema_version": 1,
                "base_ownership_sha256": lane_handoff.sha256(base),
                "inventory_sha256": lane_handoff.sha256(inventory),
                "source_reference_sha256": lane_handoff.sha256(reference),
                "overrides": [{"case_id": "HDFS-25", "from_host": "node0",
                               "to_host": "node2", "reason": "isolated node2 capacity"}],
            }
            effective_path = root / "effective-ownership.json"
            mapping_path = root / "mapping-manifest.json"
            mapping_path.write_text(json.dumps({"cases": [{
                "case_id": "HDFS-25", "promoted_sha256": "promoted",
                "healthy_result_sha256": "calibration",
                "healthy_audit_sha256": "audit",
                "status": "runtime_attested_healthy_only_full_not_started"}]}))
            effective_path.write_text(json.dumps({"owner": {"HDFS-25": "node2",
                                                               "HDFS-27": "node0",
                                                               "HDFS-28": "node0"}}))
            revision["effective_ownership_path"] = str(effective_path)
            revision["effective_ownership_sha256"] = lane_handoff.sha256(effective_path)
            revision["mapping_manifest_path"] = str(mapping_path)
            revision["mapping_manifest_sha256"] = lane_handoff.sha256(mapping_path)
            revision_path.write_text(json.dumps(revision))
            manifest = {"cases": [{"case_id": "HDFS-25",
                                    "promoted_sha256": "promoted",
                                    "calibration_sha256": "calibration",
                                    "healthy_audit_sha256": "audit"}],
                        "ownership_revision_path": str(revision_path),
                        "ownership_revision_sha256": lane_handoff.sha256(revision_path)}
            owners = lane_handoff.assignment_for_manifest(
                manifest, base, inventory, reference, "node2")
            self.assertEqual("node2", owners["HDFS-25"])
            self.assertEqual("node0", owners["HDFS-27"])
            revision["overrides"][0]["case_id"] = "HDFS-27"
            revision_path.write_text(json.dumps(revision))
            manifest["ownership_revision_sha256"] = lane_handoff.sha256(revision_path)
            with self.assertRaisesRegex(ValueError, "invalid ownership offload"):
                lane_handoff.assignment_for_manifest(
                    manifest, base, inventory, reference, "node2")
            revision_path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "hash changed"):
                lane_handoff.assignment_for_manifest(
                    manifest, base, inventory, reference, "node2")

    def test_once_waits_for_predecessor_then_runs_one_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            state = root / "state"
            case = data / "cases" / "HDFS-21"
            case.mkdir(parents=True)
            (case / "result.json").write_text("{}")
            (case / "offline-causal-audit.json").write_text("{}")
            args = argparse.Namespace(
                repo=root, data_root=data, state_root=state,
                core_release_manifest=root / "release/manifest.json",
                wait_for_tmux_exit=["previous-tmux"], wait_for_case=["HDFS-20"],
                lane_id="lane3", once=True, dry_run=False, poll_seconds=1,
                ready_manifest=root / "ready.json", inventory=root / "inventory.json",
                source_reference=root / "reference.json", host="node0",
                priority=["HDFS-21"], exclude_case=[], min_free_gib=0,
                hosts_file=root / "hosts.json", retain_expanded_scratch=True,
                stop_when_empty=False,
            )
            tmux = [types.SimpleNamespace(returncode=0),
                    types.SimpleNamespace(returncode=1),
                    types.SimpleNamespace(returncode=1)]
            with (mock.patch.object(lane_handoff, "verify_core_release", return_value={
                    "release_id": "release", "files": {}}),
                  mock.patch.object(lane_handoff.subprocess, "run", side_effect=tmux),
                  mock.patch.object(lane_handoff, "finalized",
                                    side_effect=[False, True, False]),
                  mock.patch.object(lane_handoff, "ready_cases", return_value=[{
                      "case_id": "HDFS-21", "system": "hdfs"}]),
                  mock.patch.object(lane_handoff, "run_one") as run_one,
                  mock.patch.object(lane_handoff.time, "sleep") as sleep):
                self.assertEqual(0, lane_handoff.supervise(args))
                run_one.assert_called_once()
                self.assertEqual(2, sleep.call_count)


if __name__ == "__main__":
    unittest.main()
