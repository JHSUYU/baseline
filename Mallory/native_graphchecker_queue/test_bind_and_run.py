"""Exact identity and case-scoped port review tests for native promotion."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .bind_and_run import binding_for, extend_profile
from .queue import pinned_campaign_python, validate_isolation


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


class BindAndRunTest(unittest.TestCase):
    def test_assigned_case_review_repins_exact_live_port_range(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "PortAssignment.java"
            source.write_text("thread range formula\n")
            ready = root / "ready.json"
            config_sha = "c" * 64
            write(ready, {"case_id": "ZOOKEEPER-06",
                          "case_config_sha256": config_sha,
                          "thread_id": 7, "port_range": [19297, 20642]})
            admission = root / "admission.json"
            write(admission, {"port_range": {
                "start": 19297, "end": 20642, "thread_id": 7},
                "paths_sha256": {"config": config_sha,
                                 "ready": hashlib.sha256(
                                     ready.read_bytes()).hexdigest()}})
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            review = root / "assigned-review.json"
            write(review, {"schema_version": 1,
                           "kind": "native_assigned_port_case_review",
                           "system": "zookeeper", "case_id": "ZOOKEEPER-06",
                           "native_config_sha256": config_sha,
                           "port_range": {"start": 19297, "end": 20642,
                                          "count": 1346, "thread_id": 7},
                           "required_jvm_args": [
                               "-Dzookeeper.junit.threadid=7"],
                           "source_evidence": {"path": str(source),
                                               "sha256": digest},
                           "ready": {"path": str(ready),
                                     "sha256": hashlib.sha256(
                                         ready.read_bytes()).hexdigest()},
                           "admission": {"path": str(admission),
                                         "sha256": hashlib.sha256(
                                             admission.read_bytes()).hexdigest()}})
            profile = {"schema_version": 1, "systems": {"zookeeper": {
                "required_jvm_args": [], "ports": {"mode": "assigned",
                    "evidence": {str(source): digest}, "cases": {
                        "ZOOKEEPER-06": {"start": 17951, "count": 1346,
                            "required_jvm_args": [
                                "-Dzookeeper.junit.threadid=6"]},
                        "ZOOKEEPER-08": {"start": 20643, "count": 1346,
                            "required_jvm_args": [
                                "-Dzookeeper.junit.threadid=8"]}}}}}}
            updated = extend_profile(profile, "zookeeper", "ZOOKEEPER-06",
                                     review, config_sha)
            self.assertEqual(17951, profile["systems"]["zookeeper"][
                "ports"]["cases"]["ZOOKEEPER-06"]["start"])
            self.assertEqual(19297, updated["systems"]["zookeeper"][
                "ports"]["cases"]["ZOOKEEPER-06"]["start"])
            config = {"runner": {"jvm_args": [
                "-Dzookeeper.junit.threadid=7"]}}
            with patch("Mallory.native_graphchecker_queue.queue._contains_trial_dir",
                       return_value=True):
                self.assertEqual("assigned", validate_isolation(
                    updated, "zookeeper", "ZOOKEEPER-06", config,
                    {"ZOOKEEPER-06": "node2", "ZOOKEEPER-08": "node2"},
                    "node2")["mode"])
            ready.write_text("changed\n")
            with self.assertRaisesRegex(ValueError,
                                        "assigned port ready evidence changed"):
                extend_profile(profile, "zookeeper", "ZOOKEEPER-06",
                               review, config_sha)

    def test_native_suffix_keeps_inventory_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            state = root / "campaign"
            state.mkdir()
            item = {
                "case_id": "HBASE-01",
                "system": "hbase",
                "target": {"site_id": "<C: void f()>#u224",
                           "target_exception": "E"},
                "workload": {"test_class": "OriginalTest",
                             "test_method": "testCase"},
            }
            config = {
                "case_id": "HBASE-01-native-original-v5",
                "runner": {"mode": "region_state"},
                "target_site": "<C: void f()>#u212",
                "target_throw": {"siteId": "<C: void f()>#u224",
                                 "exceptionClass": "E"},
                "junit": {"class": "OriginalTest", "method": "testCase"},
            }
            write(config_path, config)
            campaign_source = root / "campaign-python"
            campaign_source.mkdir()
            module = campaign_source / "campaign.py"
            module.write_text("pass\n")
            archive = root / "campaign-python.tar"
            archive.write_bytes(b"immutable campaign source archive")
            with patch("Mallory.native_graphchecker_queue.bind_and_run._validate_config"):
                binding = binding_for(
                    item, config_path, state,
                    campaign_python_root=campaign_source,
                    campaign_python_tar=archive)
                self.assertEqual("HBASE-01", binding["inventory_case_id"])
                self.assertEqual(config["case_id"], binding["native_case_id"])
                self.assertEqual(campaign_source, pinned_campaign_python(
                    binding["campaign_python_source"]))
                module.write_text("changed\n")
                with self.assertRaisesRegex(ValueError, "Python source changed"):
                    pinned_campaign_python(binding["campaign_python_source"])
                config["case_id"] = "HBASE-02-native-original-v5"
                write(config_path, config)
                with self.assertRaisesRegex(ValueError, "exact inventory target"):
                    binding_for(item, config_path, state)

    def test_hbase_case_review_adds_shared_source_pins(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "HBaseTestingUtility.java"
            source.write_text("ports choose zero\n")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            review = root / "port-review.json"
            write(review, {
                "schema_version": 1, "system": "hbase", "case_id": "HBASE-01",
                "mode": "source_reviewed_random_retry",
                "zk_random_port_range": [49152, 65279],
                "zk_bind_exception_retry": True,
                "hbase_cluster_default_ports_zero": True,
                "reviewed_source_sha256": {str(source): digest},
            })
            profile = {"schema_version": 1, "systems": {"hbase": {
                "ports": {"mode": "random_retry", "evidence": {}},
                "required_jvm_args": ["-Dbuild.test.dir={trial_workdir}"],
            }}}
            extended = extend_profile(profile, "hbase", "HBASE-01", review)
            self.assertEqual(str(review), extended["systems"]["hbase"][
                "ports"]["case_receipts"]["HBASE-01"])
            self.assertEqual({}, profile["systems"]["hbase"]["ports"]["evidence"])
            config = {"runner": {"jvm_args": [
                "-Djava.io.tmpdir={trial_workdir}",
                "-Dbuild.test.dir={trial_workdir}"]}}
            self.assertEqual("random_retry", validate_isolation(
                extended, "hbase", "HBASE-01", config,
                {"HBASE-01": "node2"}, "node2")["mode"])
            source.write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                validate_isolation(extended, "hbase", "HBASE-01", config,
                                   {"HBASE-01": "node2"}, "node2")


if __name__ == "__main__":
    unittest.main()
