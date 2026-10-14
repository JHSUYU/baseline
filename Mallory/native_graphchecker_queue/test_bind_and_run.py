"""Exact identity and case-scoped port review tests for native promotion."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch.checklist import _verify_alternate_junit
from .bind_and_run import (attach_shared_port_evidence, binding_for, extend_profile, promote,
                           swap_unbound_reservation)
from .queue import pinned_campaign_python, validate_isolation


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


class BindAndRunTest(unittest.TestCase):
    def test_shared_port_source_fallback_keeps_original_pin_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'other-host/MiniDFSCluster.java'
            shared = root / 'shared/MiniDFSCluster.java'
            shared.parent.mkdir()
            shared.write_text('unchanged original port-zero source\n')
            digest = hashlib.sha256(shared.read_bytes()).hexdigest()
            case_source = root / 'shared/TestOriginal.java'
            case_source.write_text('unchanged original JUnit\n')
            case_digest = hashlib.sha256(case_source.read_bytes()).hexdigest()
            review = root / 'port-review.json'
            write(review, {'schema_version': 1, 'system': 'hdfs',
                           'case_id': 'HDFS-21',
                           'all_listeners_bind_port_zero': True,
                           'evidence': {str(case_source): case_digest}})
            profile = {'schema_version': 1, 'systems': {'hdfs': {
                'required_jvm_args': [], 'ports': {
                    'mode': 'ephemeral',
                    'evidence': {str(original): digest}}}}}
            extended = extend_profile(profile, 'hdfs', 'HDFS-21', review)
            receipt = root / 'shared-port-evidence.json'
            write(receipt, {'schema_version': 1,
                            'kind': 'native_shared_port_evidence_fallback',
                            'system': 'hdfs', 'case_id': 'HDFS-21',
                            'host': 'node1',
                            'native_config_sha256': 'c' * 64,
                            'previous_isolation_sha256': 'd' * 64,
                            'replacements': [{
                                'original_path': str(original),
                                'sha256': digest,
                                'shared_path': str(shared)}]})
            attached = attach_shared_port_evidence(
                extended, profile, receipt, system='hdfs',
                case_id='HDFS-21', host='node1',
                config_sha256='c' * 64, original_sha256='d' * 64)
            self.assertEqual(profile['systems']['hdfs']['ports']['evidence'],
                             {str(original): digest})
            self.assertIn(str(original), attached['systems']['hdfs'][
                'ports']['evidence'])
            config = {'runner': {'jvm_args': [
                '-Djava.io.tmpdir={trial_workdir}',
                '-Dtest.build.data={trial_workdir}']}}
            self.assertEqual('ephemeral', validate_isolation(
                attached, 'hdfs', 'HDFS-21', config,
                {'HDFS-21': 'node1'}, 'node1')['mode'])
            shared.write_text('changed source\n')
            with self.assertRaisesRegex(ValueError, 'shared port source evidence changed'):
                validate_isolation(attached, 'hdfs', 'HDFS-21', config,
                                   {'HDFS-21': 'node1'}, 'node1')
            shared.write_text('unchanged original port-zero source\n')
            original.parent.mkdir()
            original.write_text('different local source\n')
            with self.assertRaisesRegex(ValueError, 'port isolation evidence changed'):
                validate_isolation(attached, 'hdfs', 'HDFS-21', config,
                                   {'HDFS-21': 'node1'}, 'node1')
            original.unlink()
            with self.assertRaisesRegex(ValueError, 'already attached'):
                attach_shared_port_evidence(
                    attached, profile, receipt, system='hdfs',
                    case_id='HDFS-21', host='node1',
                    config_sha256='c' * 64, original_sha256='d' * 64)

    def test_assigned_port_swap_requires_review_and_unbound_case(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, state = root / 'config', root / 'state'
            config.mkdir()
            state.mkdir()
            old = {'systems': {'zookeeper': {'ports': {
                'mode': 'assigned', 'cases': {
                    'ZOOKEEPER-09': {'start': 21989, 'count': 1346,
                                     'required_jvm_args': [
                                         '-Dzookeeper.junit.threadid=9']},
                    'ZOOKEEPER-12': {'start': 26027, 'count': 1346,
                                     'required_jvm_args': [
                                         '-Dzookeeper.junit.threadid=12']}}}}}}
            changed = json.loads(json.dumps(old))
            changed['systems']['zookeeper']['ports']['cases']['ZOOKEEPER-12'] = (
                old['systems']['zookeeper']['ports']['cases']['ZOOKEEPER-09'])
            review = root / 'unbound.json'
            observations = {}
            for checked_host in ('node0', 'node1', 'node2'):
                observation = {
                    'hostname': checked_host + '.example',
                    'matching_prepared_roots': [],
                    'matching_processes': [],
                    'matching_tmux_sessions': []}
                path = root / f'{checked_host}.json'
                write(path, observation)
                observations[checked_host] = {
                    'path': str(path),
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'observations': observation}
            write(review, {'schema_version': 1,
                           'kind': 'unbound_assigned_port_reservation_review',
                           'case_id': 'ZOOKEEPER-12',
                           'displaced_case_id': 'ZOOKEEPER-09',
                           'host': 'node0',
                           'isolation_sha256': 'a' * 64,
                           'ownership_sha256': 'b' * 64,
                           'displaced_binding_absent': True,
                           'prepared_case_root_absent': True,
                           'active_process_absent': True,
                           'checked_hosts': ['node0', 'node1', 'node2'],
                           'evidence': observations})
            args = {'case_id': 'ZOOKEEPER-12',
                    'displaced_case_id': 'ZOOKEEPER-09',
                    'host': 'node0',
                    'ownership': {'ZOOKEEPER-09': 'node0',
                                  'ZOOKEEPER-12': 'node0'},
                    'config_root': config, 'state_root': state,
                    'profile_sha256': 'a' * 64,
                    'ownership_sha256': 'b' * 64,
                    'review_path': review}
            swapped, receipt = swap_unbound_reservation(old, changed,
                                                          **args)
            self.assertEqual(swapped['systems']['zookeeper']['ports'][
                'cases']['ZOOKEEPER-09']['start'], 26027)
            self.assertEqual(receipt['unbound_review_sha256'],
                             hashlib.sha256(review.read_bytes()).hexdigest())
            write(root / 'node1.json', {'hostname': 'node1.example',
                                        'matching_processes': ['ZK09']})
            with self.assertRaisesRegex(ValueError, 'host observation changed'):
                swap_unbound_reservation(old, changed, **args)
            write(root / 'node1.json', observations['node1']['observations'])
            write(config / 'ZOOKEEPER-09.json', {})
            with self.assertRaisesRegex(ValueError, 'unbound same-host'):
                swap_unbound_reservation(old, changed, **args)

    def test_hdfs40_promotion_requires_isolated_v15_epoch(self):
        with patch("Mallory.native_graphchecker_queue.bind_and_run.physical_host"):
            with self.assertRaisesRegex(ValueError, "explicit v15"):
                promote(root=Path("/tmp/native-102-queue-v2"),
                        case_id="HDFS-40", native_config=Path("/tmp/config"),
                        native_state=Path("/tmp/state"), host="node0",
                        dispatch=False)
            with self.assertRaisesRegex(ValueError, "isolated v15"):
                promote(root=Path("/tmp/native-102-queue-v2"),
                        case_id="HDFS-40", native_config=Path("/tmp/config"),
                        native_state=Path("/tmp/state"), host="node0",
                        epoch_receipt=Path("/tmp/epoch"),
                        epoch_receipt_sha256="0" * 64, dispatch=False)

    def test_alternate_junit_shared_source_works_on_nonowner_host(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private-source"
            original_source = private / "src/TestOriginal.java"
            original_class = private / "classes/TestOriginal.class"
            source = root / "shared/TestOriginal.java"
            compiled = root / "shared/TestOriginal.class"
            source.parent.mkdir()
            source.write_text("unchanged original test\n")
            compiled.write_bytes(b"compiled unchanged test")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            resolver = root / "resolver.json"
            write(resolver, {"checkSiteId": "<C: void m()>#u4",
                             "reachedEventCount": 2})
            healthy = root / "healthy.json"
            write(healthy, {"status": "healthy_seed", "junit_passed": True,
                            "native_target_retained": True})
            attestation = root / "attestation.json"
            write(attestation, {
                "case_id": "HDFS-14",
                "binding_type": "alternate_unchanged_original_junit",
                "inventory_recorded_selector": "T#testCase",
                "executed_selector": "T#testCase[0]",
                "target_throw_site_id": "<C: void m()>#u9",
                "target_site_id": "<C: void m()>#u4",
                "healthy_junit_exit_code": 0,
                "healthy_target_reached_event_count": 2,
                "source_root": str(private), "source_commit": "a" * 40,
                "source_path": str(original_source),
                "source_sha256": digest(source),
                "compiled_test_class_path": str(original_class),
                "compiled_test_class_sha256": digest(compiled),
                "resolver_receipt_path": str(resolver),
                "resolver_receipt_sha256": digest(resolver),
                "native_official_healthy_result_path": str(healthy),
                "native_official_healthy_result_sha256": digest(healthy)})
            shared = root / "shared-source-receipt.json"
            write(shared, {
                "schema_version": 1,
                "mode": "shared_alternate_junit_source_receipt",
                "case_id": "HDFS-14",
                "attestation_path": str(attestation),
                "attestation_sha256": digest(attestation),
                "source_commit": "a" * 40,
                "source_relative_path": "src/TestOriginal.java",
                "git_blob_sha256": digest(source),
                "original_source_path": str(original_source),
                "original_source_sha256": digest(source),
                "original_compiled_class_path": str(original_class),
                "original_compiled_class_sha256": digest(compiled),
                "shared_source_path": str(source),
                "shared_source_sha256": digest(source),
                "shared_compiled_class_path": str(compiled),
                "shared_compiled_class_sha256": digest(compiled)})
            binding = root / "binding.json"
            write(binding, {"mode": "native_region_state_case_binding",
                            "alternate_original_junit": {
                                "attestation_path": str(attestation),
                                "attestation_sha256": digest(attestation),
                                "shared_source_receipt_path": str(shared),
                                "shared_source_receipt_sha256": digest(shared)}})
            item = {"case_id": "HDFS-14",
                    "workload": {"selected_selector": "T#testCase"},
                    "target": {"site_id": "<C: void m()>#u9"}}
            config = {"junit": {"class": "T", "method": "testCase[0]"},
                      "target_site": "<C: void m()>#u4"}
            _verify_alternate_junit(item, binding, config)
            compiled.write_bytes(b"altered compiled test")
            with self.assertRaisesRegex(ValueError,
                                        "alternate JUnit shared source/class changed"):
                _verify_alternate_junit(item, binding, config)
            compiled.write_bytes(b"compiled unchanged test")
            original_source.parent.mkdir(parents=True)
            original_source.write_text("changed private source\n")
            with self.assertRaisesRegex(ValueError,
                                        "alternate JUnit source_path changed"):
                _verify_alternate_junit(item, binding, config)

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
