"""HDFS adapter identity checks using source-backed frozen pilot evidence."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Mallory.native_graphchecker_dispatch import hdfs_native_adapter as adapter
from Mallory.native_graphchecker_dispatch.preparation import build_request


BASE = Path(__file__).resolve().parents[1]
INVENTORY = BASE / "cases/inventory.json"
EVIDENCE = Path("/proj/silentfailure-PG0/ZhenyuLi")


class HdfsNativeAdapterTest(unittest.TestCase):
    def test_inventory_request_binds_compiled_check_and_distinct_throw(self):
        rows = json.loads(INVENTORY.read_text())["cases"]
        item = next(row for row in rows if row["case_id"] == "HDFS-29")
        request = build_request(item, INVENTORY)
        self.assertEqual(577, request["target"]["check_sites"][0]["source_line"])
        self.assertEqual(578, request["target"]["throw_line"])
        self.assertEqual("org.apache.hadoop.hdfs.TestLeaseRecovery#testBlockSynchronization",
                         request["original_junit"]["selector"])
        self.assertEqual(item["target"]["site_id"], request["target"]["site_id"])
        self.assertNotIn("doors", request)

    def test_scope_requires_unique_guard_throw_and_static_doors(self):
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary)
            request = adapter.request_from_inventory(INVENTORY, "HDFS-29")
            site = request["target"]["site_id"]
            check = site.rsplit("#", 1)[0] + "#u4"
            targets = [
                {"kind": "BRANCH", "clazz": request["target"]["class"],
                 "method": request["target"]["method"], "line": 577,
                 "siteId": check},
                {"kind": "THROW", "clazz": request["target"]["class"],
                 "method": request["target"]["method"], "line": 578,
                 "siteId": site, "exceptionClass": "java.io.IOException"},
            ]
            manifest = {"targets": targets, "doors": [{"siteId": "original-soot-door"}]}
            (scope / "weave_manifest.json").write_text(json.dumps(manifest))
            (scope / "analysis.json").write_text(json.dumps({
                "targetSiteId": check, "throwSiteId": site,
                "analysisKind": "original_graphchecker_seed_backward"}))
            self.assertEqual((check, site),
                             adapter._target_sites(request, scope)[:2])
            manifest["doors"] = []
            (scope / "weave_manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "frontier"):
                adapter._target_sites(request, scope)
            manifest["doors"] = [{"siteId": "original-soot-door"}]
            manifest["targets"][1]["exceptionClass"] = "java.lang.AssertionError"
            (scope / "weave_manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "guard, throw"):
                adapter._target_sites(request, scope)

    def test_multiple_inventory_guards_require_selected_exact_mapping(self):
        request = adapter.request_from_inventory(INVENTORY, "HDFS-09")
        alternatives = request["target"]["check_sites"]
        self.assertEqual([503, 505], [x["source_line"] for x in alternatives])
        selected = adapter.request_from_inventory(
            INVENTORY, "HDFS-09", selected_check_mapping=alternatives[1]["mapping"])
        self.assertEqual(alternatives[1]["mapping"],
                         selected["target"]["selected_check_mapping"])
        with self.assertRaisesRegex(ValueError, "absent from the inventory"):
            adapter.request_from_inventory(INVENTORY, "HDFS-09",
                                           selected_check_mapping="unknown")
        same_line = adapter.request_from_inventory(INVENTORY, "HDFS-01")
        with tempfile.TemporaryDirectory() as temporary:
            scope = Path(temporary)
            target = same_line["target"]
            (scope / "weave_manifest.json").write_text(json.dumps({
                "targets": [{"kind": "BRANCH", "clazz": target["class"],
                             "method": target["method"], "line": 517,
                             "siteId": "one-soot-unit"}],
                "doors": [{"siteId": "original-soot-door"}]}))
            (scope / "analysis.json").write_text(json.dumps({
                "targetSiteId": "one-soot-unit"}))
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                adapter._target_sites(same_line, scope)

    def test_hdfs30_requires_explicit_alternate_junit_attestation(self):
        static = EVIDENCE / "mallory-hdfs30-native-static-v1"
        if not static.is_dir():
            self.skipTest("frozen HDFS-30 evidence is unavailable")
        attestation = static / "alternate-selector-source-preparation.json"
        inventory = adapter.request_from_inventory(INVENTORY, "HDFS-30")
        self.assertIn("TestPipelinesFailover#", inventory["original_junit"]["selector"])
        selected = adapter.request_from_inventory(INVENTORY, "HDFS-30", attestation)
        self.assertEqual("org.apache.hadoop.hdfs.TestLeaseRecovery#testBlockSynchronization",
                         selected["original_junit"]["selector"])
        with tempfile.TemporaryDirectory() as temporary:
            tampered = json.loads(attestation.read_text())
            tampered["target_throw_source_line"] = 999
            path = Path(temporary) / "attestation.json"
            path.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "attestation"):
                adapter.request_from_inventory(INVENTORY, "HDFS-30", path)

    def test_hdfs30_official_alternate_junit_binding(self):
        healthy = EVIDENCE / "mallory-hdfs30-native-healthy-v1"
        attestation = healthy / "alternate-selector-attestation.json"
        if not attestation.is_file():
            self.skipTest("frozen official HDFS-30 attestation is unavailable")
        request = adapter.request_from_inventory(INVENTORY, "HDFS-30",
                                                 attestation)
        self.assertEqual("org.apache.hadoop.hdfs.TestLeaseRecovery#testBlockSynchronization",
                         request["original_junit"]["selector"])
        with tempfile.TemporaryDirectory() as temporary:
            tampered = json.loads(attestation.read_text())
            tampered["native_official_healthy_result_sha256"] = "0" * 64
            path = Path(temporary) / "attestation.json"
            path.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "attestation"):
                adapter.request_from_inventory(INVENTORY, "HDFS-30", path)

    def test_prepare_derives_static_guard_and_junit_without_doors(self):
        request = adapter.request_from_inventory(INVENTORY, "HDFS-29")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_file = root / "request.json"
            request_file.write_text(json.dumps(request))
            profile = {"java": "/pinned/java", "process_classes": "/pinned/classes",
                       "analysis_classpath": ["/pinned/classes", "/pinned/lib.jar"],
                       "planner_classpath": ["/pinned/planner.jar"],
                       "communication_mappings": "/pinned/mappings.jsonl"}
            def stop_at_static(stage, command, output, timeout, *args):
                self.assertEqual("static", stage)
                self.assertEqual("edu.uva.liftlab.mallory.scope.ScopePlanner",
                                 command[-3])
                raise RuntimeError("static command captured")
            with mock.patch.object(adapter, "_profile", return_value=profile), \
                 mock.patch.object(adapter, "_run", side_effect=stop_at_static):
                with self.assertRaisesRegex(RuntimeError, "captured"):
                    adapter.prepare(request_file, root / "profile.json",
                                    root / "output")
            scope = json.loads((root / "output/static/scope-input.json").read_text())
            self.assertEqual(577, scope["target"]["check_line"])
            self.assertEqual(578, scope["target"]["throw_line"])
            self.assertEqual("testBlockSynchronization",
                             scope["workload"]["method"])
            self.assertNotIn("doors", scope)

    def test_static_reuse_requires_exact_original_command_and_copies_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prior/static"
            destination = root / "next/static"
            for name in ("original-scope", "static-scope"):
                (source / name).mkdir(parents=True)
                (source / name / "output.jsonl").write_text(name)
            (source.parent / "commands").mkdir()
            (source.parent / "commands/static.stderr").write_text("closed\n")
            source_input = {"case_id": "HDFS-32", "analysis": {
                "original_engine_output_dir": str(source / "original-scope")}}
            (source / "scope-input.json").write_text(json.dumps(source_input))
            prior_command = ["java", "ScopePlanner", str(source / "scope-input.json"),
                             str(source / "static-scope")]
            (source.parent / "commands/static.json").write_text(json.dumps({
                "argv": prior_command}))
            expected_input = {"case_id": "HDFS-32", "analysis": {
                "original_engine_output_dir": str(destination / "original-scope")}}
            new_command = ["java", "ScopePlanner", str(destination / "scope-input.json"),
                           str(destination / "static-scope")]
            destination.mkdir(parents=True)
            adapter._reuse_static(source, destination, expected_input,
                                  new_command, root / "next")
            self.assertEqual("original-scope", (destination /
                             "original-scope/output.jsonl").read_text())
            self.assertTrue((root / "next/static-reuse-receipt.json").is_file())
            with self.assertRaisesRegex(ValueError, "differs"):
                adapter._reuse_static(source, root / "other", expected_input,
                                      ["changed", *new_command[1:]], root / "other")

    def test_frozen_hdfs29_and_30_original_pipeline_read_only(self):
        for number in (29, 30):
            with self.subTest(case=number):
                static = EVIDENCE / f"mallory-hdfs{number}-native-static-v1"
                healthy = EVIDENCE / f"mallory-hdfs{number}-native-healthy-v1"
                if not static.is_dir() or not healthy.is_dir():
                    self.skipTest("frozen HDFS evidence is unavailable")
                attestation = (healthy / "alternate-selector-attestation.json"
                               if number == 30 else None)
                request = adapter.request_from_inventory(
                    INVENTORY, f"HDFS-{number}", attestation)
                result = adapter.verify_existing(request, static, healthy)
                self.assertEqual("verified_existing_original_pipeline",
                                 result["status"])
                self.assertEqual(239, result["static_door_count"])
                self.assertEqual("", (static / "original-scope/io_doors.jsonl")
                                 .read_text())
                self.assertNotEqual(result["check_site_id"],
                                    result["throw_site_id"])


if __name__ == "__main__":
    unittest.main()
